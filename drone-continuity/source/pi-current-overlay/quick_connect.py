"""Single-use, short-lived browser pairing via a same-UID Unix socket."""
import hashlib
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
from pathlib import Path

PATH = Path('/run/user/1000/axl-field-pair/pair.sock')
PREFIX = 'https://orangepi-drone.local:8446/#join='


class PairingCodes:
    def __init__(self, expires_unix, clock=time.monotonic, wall=time.time):
        self.expires_unix, self.clock, self.wall = expires_unix, clock, wall
        self.lock = threading.Lock()
        self.digest, self.deadline, self.last_issue = '', 0, float('-inf')

    def issue(self):
        with self.lock:
            now = self.clock()
            if self.wall() >= self.expires_unix:
                raise ValueError('Owner access expired')
            if now - self.last_issue < 2:
                raise ValueError('Wait before refreshing')
            token = secrets.token_urlsafe(32)
            self.digest = hashlib.sha256(token.encode()).hexdigest()
            ttl = min(120, int(self.expires_unix-self.wall()))
            if ttl < 1:
                raise ValueError('Owner access expired')
            self.deadline, self.last_issue = now+ttl, now
            return {'ok': True, 'url': PREFIX+token, 'expires_seconds': ttl,
                    'single_use': True, 'scope': 'private_field_dashboard'}

    def consume(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return False
        with self.lock:
            valid = (self.wall() < self.expires_unix and self.clock() < self.deadline
                     and secrets.compare_digest(self.digest, hashlib.sha256(token.encode()).hexdigest()))
            if valid:
                self.digest, self.deadline = '', 0
            return valid


def request_code():
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(PATH))
        client.sendall(b'issue\n')
        data = b''
        while len(data) < 1024:
            chunk = client.recv(1024-len(data))
            if not chunk:
                break
            data += chunk
        value = json.loads(data)
        if not value.get('ok'):
            raise ValueError('Pairing unavailable')
        return value


def start_pairing_bridge(codes, stop):
    # Bind synchronously so startup fails visibly on a sandbox/path error.
    PATH.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(PATH))
    os.chmod(PATH, 0o600)
    listener.listen(2)
    listener.settimeout(1)

    def serve():
        with listener:
            while not stop.is_set():
                try:
                    client, _ = listener.accept()
                except socket.timeout:
                    continue
                with client:
                    try:
                        client.settimeout(2)
                        _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        if uid != os.getuid() or client.recv(32) != b'issue\n':
                            continue
                        try:
                            value = codes.issue()
                        except ValueError:
                            value = {'ok': False}
                        client.sendall(json.dumps(value).encode())
                    except OSError:
                        pass
    threading.Thread(target=serve, name='display-browser-pairing', daemon=True).start()
