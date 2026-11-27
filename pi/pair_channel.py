"""Authenticated endpoint for a single enrolled touchscreen's wired desktop."""
import hashlib
import hmac
import re
import secrets
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CONTEXT = b"WiredDesktopPair/v1"
HELLO, SCREEN_PROOF, PI_PROOF, DOWN, UP = range(0x60, 0x65)
READY = b"\x20"
HANDSHAKE_SECONDS = 12
SESSION_SECONDS = 295


def pi_inner_key(seed, serial):
    if not isinstance(seed, bytes) or len(seed) != 32 or not any(seed):
        raise ValueError("Invalid enrolled Pi seed.")
    if not isinstance(serial, str) or not re.fullmatch(r"[0-9a-f]{16,64}", serial):
        raise ValueError("Invalid Pi hardware identifier.")
    return hmac.digest(seed, b"wired-pi-v1\0" + serial.encode("ascii"), hashlib.sha256)


def screen_pair_key(inner, mac):
    if not isinstance(inner, bytes) or len(inner) != 32 or not isinstance(mac, bytes) or len(mac) != 6:
        raise ValueError("Invalid screen enrollment.")
    return hmac.digest(inner, b"wired-screen-v1\0" + mac, hashlib.sha256)


class PiChannel:
    def __init__(self, pair_key_32, *, clock=time.monotonic, random=secrets.token_bytes):
        if not isinstance(pair_key_32, bytes) or len(pair_key_32) != 32 or not any(pair_key_32):
            raise ValueError("A provisioned 32-byte pair credential is required.")
        self._key = pair_key_32
        self._clock, self._random = clock, random
        self.reset()

    def reset(self):
        self._np = self._ns = self._pi_proof = None
        self._down = self._up = None
        self.tx_counter = self.rx_counter = 0
        self._ready = False
        self._deadline = 0

    @property
    def ready(self):
        return self._ready and self._clock() < self._deadline

    def hello(self):
        """Begin a new session. Keep the returned bytes for wire retries."""
        self.reset()
        self._np = self._random(16)
        if len(self._np) != 16:
            raise ValueError("Invalid nonce source.")
        self._deadline = self._clock() + HANDSHAKE_SECONDS
        return bytes((HELLO,)) + self._np

    def _proof(self, label, ns):
        return hmac.digest(self._key, CONTEXT + label + self._np + ns, hashlib.sha256)[:16]

    def accept(self, screen_proof):
        if self._np is None or self.ready or self._clock() >= self._deadline:
            return None
        if len(screen_proof) != 33 or screen_proof[0] != SCREEN_PROOF:
            return None
        ns = screen_proof[1:17]
        if not hmac.compare_digest(screen_proof[17:], self._proof(b"S", ns)):
            return None
        if self._ns is not None:
            return self._pi_proof if hmac.compare_digest(ns, self._ns) else None
        self._ns = ns
        keys = HKDF(algorithm=SHA256(), length=80, salt=self._np + ns, info=CONTEXT).derive(self._key)
        self._down = AESGCM(keys[:32]), keys[64:72]
        self._up = AESGCM(keys[32:64]), keys[72:80]
        self._pi_proof = bytes((PI_PROOF,)) + self._proof(b"P", ns)
        return self._pi_proof

    def wrap(self, clear_bytes):
        if not self.ready or not 1 <= len(clear_bytes) <= 40 or self.tx_counter >= 0xffffffff:
            raise ValueError("Paired desktop is unavailable or record size is invalid.")
        self.tx_counter += 1
        header = bytes((DOWN,)) + self.tx_counter.to_bytes(4, "big")
        cipher, prefix = self._down
        return header + cipher.encrypt(prefix + header[1:], bytes(clear_bytes), header)

    def unwrap(self, up_record):
        if self._up is None or self._clock() >= self._deadline:
            return None
        if not 22 <= len(up_record) <= 56 or up_record[0] != UP:
            return None
        header = up_record[:5]
        counter = int.from_bytes(header[1:], "big")
        if counter <= self.rx_counter:
            return None
        cipher, prefix = self._up
        try:
            clear = cipher.decrypt(prefix + header[1:], up_record[5:], header)
        except InvalidTag:
            return None
        if not self._ready:
            if clear != READY or counter != 1:
                return None
            self._ready = True
            self._deadline = self._clock() + SESSION_SECONDS
        elif clear == READY:
            return None
        self.rx_counter = counter
        return clear
