"""Verify the configured SSH identity before connecting the receive-only telemetry route."""
import base64
import hashlib
import ipaddress
import json
from pathlib import Path
import queue
import re
import secrets
import socket
import subprocess
import threading
import time


FIFO = "/run/orangepi-mavlink/pc-h743.fifo"
READY = b"PC_H743_RECEIVER_READY_V1\n"
CALIBRATE = b"PC_H743_RECEIVER_CLOCK_V1\n"
MODEL = "Orange Pi Zero 3W"



RECEIVER_SHA = "af4912423056bb0ae97b36c2f498bc3e8252417d385646cb88cd215e4da5661a"
FRAME_SHA = "019608185d1a308807f0f9db84c6344c3559ad6be8012806ed32800d9cf8d18f"


def valid_peer(peer):
    if not isinstance(peer, str) or len(peer) > 253:
        return False
    try:
        address, _, zone = peer.partition("%")
        ip = ipaddress.ip_address(address)
        return not (ip.is_unspecified or ip.is_loopback or ip.is_multicast) and (
            not zone or (ip.version == 6 and re.fullmatch(r"[A-Za-z0-9_.-]+", zone) is not None))
    except ValueError:
        return all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", x)
                   for x in peer.split("."))



def saved_route(config):
    if not isinstance(config, dict):
        raise ValueError("Invalid private bridge profile")
    peers = config["ssh_candidates"]
    user = config["ssh_user"]
    if not isinstance(user, str) or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) is None:
        raise ValueError("Enter the Unix account that runs the telemetry receiver")
    if not isinstance(peers, list) or not peers or not all(valid_peer(peer) for peer in peers):
        raise ValueError("Enter the private addresses or names of the paired Pi")
    key = Path(config["identity_file"]).expanduser()
    known = Path(config["known_hosts_file"]).expanduser()
    if not key.is_absolute() or not known.is_absolute() or not key.is_file() or not known.is_file():
        raise ValueError("Choose the local OpenSSH identity and known-hosts files")
    if any(char in known.as_posix() for char in ('"', '\n', '\r', '%')):
        raise ValueError("Unsupported character in the known-hosts filename")
    alias = config["known_host_alias"]
    if not valid_peer(alias):
        raise ValueError("Enter the already-verified host name in known_hosts")
    extra = []
    scoped = config.get("windows_link_local")
    if scoped:
        addr = ipaddress.IPv6Address(scoped["address"])
        if not addr.is_link_local or "%" in str(addr):
            raise ValueError("Invalid link-local IPv6 candidate")
        try:
            index = socket.if_nametoindex(scoped["interface_name"])
        except OSError:
            pass
        else:
            extra.append(f"{addr}%{index}")


    record = subprocess.run(["ssh-keygen", "-F", alias, "-f", str(known)],
                            capture_output=True, text=True, timeout=3,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if record.returncode:
        raise ValueError("The saved SSH host key could not be verified")
    lines = [line.split() for line in record.stdout.splitlines() if not line.startswith("#")]
    keys = {parts[2] for parts in lines if len(parts) == 3 and parts[1] == "ssh-ed25519"}
    if len(keys) != 1:
        raise ValueError("The saved SSH host key could not be verified")
    digest = hashlib.sha256(base64.b64decode(keys.pop(), validate=True)).digest()
    fingerprint = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    if fingerprint != config["host_key_sha256"]:
        raise ValueError("The saved SSH host key could not be verified")
    # Never inherit forwarding, proxy or multiplexing from a personal SSH config.
    options = ["ssh", "-T", "-F", "none", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
               "-o", "StrictHostKeyChecking=yes", "-o", "UpdateHostKeys=no",
               "-o", "HostKeyAlgorithms=ssh-ed25519", "-o", "HostKeyAlias=" + alias,
               "-o", 'UserKnownHostsFile="' + known.as_posix() + '"', "-o", "GlobalKnownHostsFile=none",
               "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no", "-o", "ConnectionAttempts=1",
               "-o", "ConnectTimeout=4", "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
               "-o", "LogLevel=ERROR", "-i", str(key), "-l", user]
    return list(dict.fromkeys(extra + peers)), options


def private_profile(path):
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    serial_number = value["usb_serial"]
    if not isinstance(serial_number, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{4,80}", serial_number):
        raise ValueError("Invalid controller identity")
    return serial_number, value


def matching_ports(ports, identity):
    return [port for port in ports if (port.vid, port.pid, port.serial_number) == (0x1209, 0x5741, identity)]


# Fixed, unprivileged bootstrap. A ready marker confirms access to the reviewed
# receiver and its enabled transport. Monitor heartbeats independently prove delivery.
BOOTSTRAP = r"""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
def verified_route(model, config, receiver, frame):
    return (model.rstrip(b"\0\r\n") == b"Orange Pi Zero 3W" and
            hashlib.sha256(receiver).hexdigest() == "RECEIVER_HASH" and
            hashlib.sha256(frame).hexdigest() == "FRAME_HASH" and
            any(t.get("enabled") is True and t.get("kind") == "serial" and
                t.get("device") == "/run/orangepi-mavlink/pc-h743.fifo" and
                t.get("baud") == 115200 for t in config["transports"]))
def observe_status(s, now):
    path = s.get("transport")
    name = "fifo" if path == "/run/orangepi-mavlink/pc-h743.fifo" else "native" if path == "/dev/h743" else "other"
    hb, updated = s.get("heartbeat_updated_unix"), s.get("updated_unix")
    source = s.get("h743_source")
    valid = (name == "fifo" and s.get("connected") is True and
             s.get("authority") == "read_only_no_mavlink_transmit" and
             isinstance(source,dict) and source == s.get("expected_source") and
             all(type(source.get(k)) is int and 1 <= source[k] <= 255 for k in ("system_id","component_id")) and
             all(type(v) in (int,float) and 0 <= now - v <= 2 for v in (hb,updated)))
    return name, hb if valid else None
def watch_monitor(parent):
    last = None
    consecutive = 0
    status = Path("/run/orangepi-mavlink/status.json")
    while os.getppid() == parent:
        try:
            value = json.loads(status.read_text())
            now = time.time()
            name, stamp = observe_status(value, now)
        except (ValueError, OSError, TypeError, AttributeError):
            now, name, stamp = time.time(), "other", None
        if stamp is None:
            consecutive = 0
        elif last is None or stamp < last:
            consecutive = 1
        elif stamp > last:
            consecutive += 1
        last = stamp
        item = json.dumps([now, name, stamp, consecutive], separators=(",", ":")).encode()
        os.write(1, b"S " + item + b"\n")
        time.sleep(.45)
def bootstrap():
    receiver = Path.home() / "bin" / "pc-h743-input.py"
    frame = receiver.with_name("pc_bridge_frame.py")
    config = json.loads(Path("/etc/orangepi-mavlink-monitor.json").read_text())
    if not verified_route(Path("/proc/device-tree/model").read_bytes(), config,
                          receiver.read_bytes(), frame.read_bytes()):
        raise SystemExit(1)
    if subprocess.run(["systemctl","is-active","--quiet","orangepi-mavlink-monitor.service"]).returncode:
        raise SystemExit(1)
    sys.stdout.buffer.write(b"PC_H743_RECEIVER_CLOCK_V1\n")
    sys.stdout.buffer.flush()
    for _ in range(3):
        challenge = sys.stdin.buffer.readline(64)
        if not re.fullmatch(rb"C [0-9a-f]{24}\n", challenge):
            raise SystemExit(1)
        stamp = time.time_ns()
        sys.stdout.buffer.write(b"T " + challenge[2:-1] + b" " + str(stamp).encode() + b"\n")
        sys.stdout.buffer.flush()
    if sys.stdin.buffer.readline(16) != b"GO\n":
        raise SystemExit(1)
    sys.stdout.buffer.write(b"PC_H743_RECEIVER_READY_V1\n")
    sys.stdout.buffer.flush()
    parent = os.getpid()
    if os.fork() == 0:
        try:
            os.close(0)
            watch_monitor(parent)
        finally:
            os._exit(0)
    os.execv("/usr/bin/python3", ["python3", "-B", str(receiver)])
bootstrap()
"""


def receiver_command():
    source = BOOTSTRAP.replace("RECEIVER_HASH", RECEIVER_SHA).replace("FRAME_HASH", FRAME_SHA)
    payload = base64.b64encode(source.encode("ascii")).decode("ascii")
    return "/usr/bin/python3 -B -c \"import base64;exec(base64.b64decode('" + payload + "'))\""


def close_receiver(child):
    if child is None:
        return
    try:
        child.stdin.close()
    except (OSError, ValueError):
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=3)
    child.stdout.close()


class CaptureClock:
    def __init__(self, samples):
        # A remote timestamp lies between the two host monotonic observations.
        # All accepted offset intervals must agree, allowing 10 ms timer noise.
        valid = [(t0, t1, remote) for t0, t1, remote in samples if 0 <= t1 - t0 <= .50]
        if len(valid) < 2:
            raise ValueError("Receiver clock round trip exceeded bound")
        low = max(remote - t1 for t0, t1, remote in valid)
        high = min(remote - t0 for t0, t1, remote in valid)
        if low - high > .010:
            raise ValueError("Receiver clock changed during calibration")
        self.offset = (low + high) / 2
        self.rtt = min(t1 - t0 for t0, t1, remote in valid)
        self.started = time.monotonic()
        self.wall = time.time()

    def epoch(self, captured):
        return captured + self.offset

    def current(self, now):
        elapsed = now - self.started
        return 0 <= elapsed <= 300 and abs(time.time() - self.wall - elapsed) <= 1


class PiReceipts:
    def __init__(self, clock):
        self.clock = clock
        self.latest = None
        self.thread = None

    def accept(self, line, now):
        if not line.startswith(b"S ") or len(line) > 160:
            return
        try:
            sampled, transport, stamp, count = json.loads(line[2:])
            remote_now = self.clock.epoch(now)
            if type(sampled) not in (int,float) or not -.3 <= remote_now - sampled <= 2:
                return
            if transport not in ("fifo","native","other") or type(count) is not int or count < 0:
                return
            if stamp is not None and (type(stamp) not in (int,float) or not 0 <= sampled - stamp <= 2):
                return
            if self.latest and sampled <= self.latest[0]:
                return
            self.latest = sampled, transport, stamp, count
        except (ValueError, TypeError, UnicodeError):
            pass

    def status(self, now):
        remote_now = self.clock.epoch(now)
        value = self.latest
        recent = bool(value and -.3 <= remote_now - value[0] <= 2)
        transport = value[1] if recent else "unknown"
        stamp = value[2] if recent else None
        valid = stamp is not None and transport == "fifo" and -.3 <= remote_now - stamp <= 2
        return dict(pi_status_fresh=recent, pi_selected=transport, pi_fifo_verified=bool(valid and value[3] >= 2),
                    pi_distinct_heartbeats=value[3] if valid else 0,
                    pi_heartbeat_age_s=round(remote_now-stamp, 2) if valid else None)

    def start(self, pipe):
        def read():
            try:
                while True:
                    line = pipe.readline(161)
                    if not line:
                        return
                    self.accept(line, time.monotonic())
            except (OSError, ValueError):
                pass
        self.thread = threading.Thread(target=read, daemon=True)
        self.thread.start()


def open_receiver(options, peer, stop_requested):
    child = subprocess.Popen([*options, peer, receiver_command()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    answer = queue.Queue()
    def read_markers():
        try:
            for _ in range(5):
                line = child.stdout.readline(100)
                answer.put((line, time.monotonic()))
                if line == READY or not line:
                    return
        except (OSError, ValueError):
            answer.put((b"", time.monotonic()))
    def take_line(seconds):
        deadline = time.monotonic() + seconds
        while not stop_requested() and time.monotonic() < deadline:
            try:
                return answer.get(timeout=min(.1, max(.001, deadline - time.monotonic())))
            except queue.Empty:
                continue
        return b"", time.monotonic()
    thread = threading.Thread(target=read_markers, daemon=True)
    thread.start()
    accepted = False
    try:
        if take_line(8)[0] != CALIBRATE:
            return None
        samples = []
        for _ in range(3):
            nonce = secrets.token_hex(12).encode("ascii")
            sent = time.monotonic()
            child.stdin.write(b"C " + nonce + b"\n")
            child.stdin.flush()
            reply, received = take_line(1.2)
            checked = re.fullmatch(rb"T " + nonce + rb" ([0-9]{18,20})\n", reply)
            if not checked:
                return None
            samples.append((sent, received, int(checked[1]) / 1_000_000_000))
        child.capture_clock = CaptureClock(samples)
        child.stdin.write(b"GO\n")
        child.stdin.flush()
        accepted = take_line(1.2)[0] == READY and child.poll() is None
        if accepted:
            child.pi_receipts = PiReceipts(child.capture_clock)
            child.pi_receipts.start(child.stdout)
            return child
    finally:
        if not accepted:
            if child.poll() is None:
                child.kill()
            close_receiver(child)
        thread.join(timeout=1)
    return None
