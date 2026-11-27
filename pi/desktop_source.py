"""Access the installed owner desktop through its protected local guard."""
import base64
import getpass
import hashlib
import hmac
import io
import json
import os
import queue
import re
import secrets
import socket
import stat
import struct
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from display_model import fit_frame, synthetic_frame


def capability_valid(value, config, now):
    if value.startswith("https://"):
        value = urlsplit(value).fragment
    if not re.fullmatch("[0-9a-f]{64}", value):
        return False
    return (now < float(config["expires_unix"])
            and hmac.compare_digest(hashlib.sha256(value.encode()).hexdigest(), config["token_sha256"]))


class OwnerDesktop:
    input_interval=.041  # The installed owner broker enforces 40 ms between accepted inputs.
    def __init__(self):
        self.uid = os.getuid()
        if self.uid == 0:
            raise RuntimeError("Start as the signed-in desktop owner.")
        self.socket = Path("/run/user") / str(self.uid) / "axl-display-bridge/desktop.sock"
        self.owner = secrets.token_hex(32)
        self.event = 0
        self.base = ""

    def authorize(self):
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise RuntimeError("An interactive owner terminal is required.")
        path = Path.home() / ".config/orangepi-companion/field-setup.json"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as file:
            props = os.fstat(fd)
            if not stat.S_ISREG(props.st_mode) or props.st_uid not in (0, self.uid) or props.st_mode & 0o077:
                raise RuntimeError("Owner configuration permissions could not be verified.")
            config = json.loads(file.read(65536))
        value = getpass.getpass("To share this desktop for five minutes, enter your private owner field link: ")
        if not capability_valid(value.strip(), config, time.time()):
            raise PermissionError("Owner access was denied or expired.")
        del value
        self.deadline = min(time.monotonic() + 295, time.monotonic() + config["expires_unix"] - time.time())

    def call(self, action, **values):
        if action != "lock" and time.monotonic() >= self.deadline:
            raise PermissionError("Owner session expired.")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(2.5)
            try:
                peer.connect(str(self.socket))
            except (FileNotFoundError, ConnectionRefusedError):
                raise DesktopUnavailable(3) from None
            _, uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != self.uid or stat.S_IMODE(self.socket.stat().st_mode) != 0o600:
                raise RuntimeError("Installed owner desktop broker identity could not be verified.")
            peer.sendall(json.dumps(dict(values, action=action, owner=self.owner)).encode() + b"\n")
            with peer.makefile("rb") as data:
                raw = data.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise RuntimeError("Desktop response exceeded its limit.")
            result = json.loads(raw)
        if result.get("ok") is not True:
            if result.get("locked") is True and result.get("error") in (
                    "Fresh matching disarmed controller status required",
                    "Owner access locked: flight status is unsafe or stale"):
                raise DesktopUnavailable(2)
            raise PermissionError("The installed desktop broker refused this session or command.")
        return result

    def open(self):
        if self.call("unlock").get("owner_enabled") is not True:
            raise PermissionError("Explicit desktop unlock failed.")

    def frame(self):
        result = self.call("frame", base=self.base)
        identity = result["frame_id"]
        if identity == self.base:
            return None
        raw = base64.b64decode(result["jpeg"], validate=True)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError("Desktop frame did not match its digest.")
        with Image.open(io.BytesIO(raw), formats=("JPEG",)) as image:
            if image.size != (result["width"], result["height"]) or not (1 <= image.width <= 960 and 1 <= image.height <= 720):
                raise ValueError("Unexpected desktop dimensions.")
            fitted = fit_frame(image,native=True)
        self.base = identity
        return fitted

    def focus(self):
        reply=self.call("focus")
        return reply.get("focus_revision") if reply.get("focus_known") is True else None

    def input(self, command,focus=None):
        self.event += 1
        if focus is None:
            self.call("input", event_id=self.event, command=command)
            return True
        response=self.call("input",event_id=self.event,command=command,focus_revision=focus)
        return response.get("input_applied") is True

    def close(self):
        self.call("lock")


class DesktopUnavailable(PermissionError):
    def __init__(self,reason):
        super().__init__("Desktop sharing is paused.")
        self.reason=reason

class Pattern:
    """Exercises the same pixel/input path without accessing any OS desktop."""
    def __init__(self):
        self.pressed = False
        self.dirty = True

    def authorize(self): pass
    def open(self): pass
    def close(self): pass

    def frame(self):
        if self.dirty:
            self.dirty = False
            return fit_frame(synthetic_frame(self.pressed))
        return None

    def input(self, command):
        if command["type"] == "tap" and 80 <= round(command["x"] * 479 / 10000) <= 175 and 64 <= round(command["y"] * 295 / 10000) <= 139:
            self.pressed = not self.pressed
            self.dirty = True
            print("Pattern tap accepted.", flush=True)


class FocusRequest:
    def __init__(self,command=None,revision=None):
        self.command=command;self.revision=revision
        self.result=None;self.done=threading.Event()

class CaptureQueue(queue.Queue):
    """External drawing can wake capture without consuming an input slot."""
    def __init__(self):
        super().__init__(maxsize=8)
        self.activity = threading.Event()

    def _put(self, item):
        super()._put(item)
        self.activity.set()

    def next_command(self, timeout):
        if self.empty():
            self.activity.wait(timeout)
        return self.get_nowait()


class FrameWorker:
    """Exchange serial data independently while the safeguarded backend captures a frame."""
    def __init__(self, source, *, direct_display=False):
        self.source = source
        self.stop = threading.Event()
        self.commands = CaptureQueue() if direct_display else queue.Queue(maxsize=8)
        self.lock = threading.Lock()
        self.frame, self.view = None, None
        self.frame_id = 0
        self.confirmed = 0.0
        self.error = False
        self.failure_reason = 0
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        watcher = None
        try:
            self.source.open()
            direct = isinstance(self.commands, CaptureQueue)
            if direct:
                try:
                    from display_damage import DamageWake
                    watcher = DamageWake(self.commands.activity)
                except (ImportError, OSError):
                    pass
            burst_until=0
            input_at=0
            def dispatch(command):
                nonlocal input_at,burst_until
                spacing=getattr(self.source,"input_interval",0)
                remaining=spacing-(time.monotonic()-input_at)
                if remaining>0 and self.stop.wait(remaining):return
                if self.stop.is_set():return
                if isinstance(command,FocusRequest):
                    try:
                        command.result=(self.source.focus() if command.command is None else
                                        self.source.input(command.command,command.revision))
                    finally:
                        command.command=None
                        command.done.set()
                else:self.source.input(command)
                input_at=time.monotonic()
                burst_until=input_at+.8
            while not self.stop.is_set():
                if direct:
                    self.commands.activity.clear()
                # Avoid putting another capture in front of commands already queued.
                # Two inputs per cycle still guarantee a fresh guarded capture under load.
                for _ in range(2):
                    try:command=self.commands.get_nowait()
                    except queue.Empty:break
                    if self.stop.is_set():break
                    dispatch(command)
                if self.stop.is_set():break
                captured = self.source.frame()
                with self.lock:
                    if captured:
                        self.frame, self.view = captured
                        self.frame_id += 1
                    self.confirmed = time.monotonic()
                self.ready.set()
                try:
                    timeout = .09 if time.monotonic()<burst_until else .4
                    command = self.commands.next_command(timeout) if direct else self.commands.get(timeout=timeout)
                except queue.Empty:
                    continue
                if not self.stop.is_set():
                    dispatch(command)
        except Exception as exc:
            with self.lock:
                self.error = True
                self.failure_reason = exc.reason if isinstance(exc,DesktopUnavailable) else 0
            self.ready.set()
        finally:
            try:
                self.source.close()
            except Exception:
                pass
            if watcher:
                watcher.close()

    def snapshot(self):
        with self.lock:
            if self.error and self.failure_reason:
                raise DesktopUnavailable(self.failure_reason)
            if self.error or (self.confirmed and time.monotonic() - self.confirmed > 1.8):
                raise RuntimeError("Owner desktop authorization or fresh frames are unavailable.")
            return self.frame_id, self.frame, self.view
