"""Wake the guarded capture worker on local X11 drawing. Only a fixed byte leaves this process."""
import ctypes as C
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time


class DamageWake:
    def __init__(self, activity, display=":0"):
        self.activity = activity
        self.child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), display],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, bufsize=0)
        self.reader = threading.Thread(target=self._receive, daemon=True)
        self.reader.start()

    def _receive(self):
        while self.child.stdout.read(1) == b".":
            self.activity.set()

    def close(self):
        if self.child.poll() is None:
            self.child.terminate()
        try:
            self.child.wait(timeout=0.75)
        except subprocess.TimeoutExpired:
            self.child.kill()
            self.child.wait(timeout=1)
        self.reader.join(timeout=1)
        self.child.stdout.close()


def observe(display):
    if not re.fullmatch(r":[0-9]{1,5}", display):
        return 1
    # An abrupt service or SSH-test exit must also release the X connection.
    parent = os.getppid()
    if parent == 1 or C.CDLL(None).prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent:
        return 1
    x = C.CDLL("libX11.so.6")
    d = C.CDLL("libXdamage.so.1")
    def bind(lib, name, result, *args):
        fn = getattr(lib, name)
        fn.restype, fn.argtypes = result, args
        return fn
    ptr, integer, xid = C.c_void_p, C.c_int, C.c_ulong
    int_ptr = C.POINTER(integer)
    open_display = bind(x, "XOpenDisplay", ptr, C.c_char_p)
    root = bind(x, "XDefaultRootWindow", xid, ptr)
    next_event = bind(x, "XNextEvent", integer, ptr, ptr)
    sync = bind(x, "XSync", integer, ptr, integer)
    extension = bind(d, "XDamageQueryExtension", integer, ptr, int_ptr, int_ptr)
    version = bind(d, "XDamageQueryVersion", integer, ptr, int_ptr, int_ptr)
    create = bind(d, "XDamageCreate", xid, ptr, xid, integer)
    subtract = bind(d, "XDamageSubtract", None, ptr, xid, xid, xid)
    conn = open_display(display.encode("ascii"))
    if not conn:
        return 1
    base, error, major, minor = integer(), integer(), integer(), integer()
    if not extension(conn, C.byref(base), C.byref(error)) or not version(conn, C.byref(major), C.byref(minor)):
        return 1
    # NonEmpty emits once until we subtract accumulated damage. No pixels,
    # keyboard data, coordinates or window properties are read.
    damage = create(conn, root(conn), 3)
    if not damage:
        return 1
    sync(conn, 0)
    event = (C.c_long * 24)()
    last = 0.0
    while True:
        next_event(conn, C.byref(event))
        if C.cast(event, int_ptr)[0] != base.value:
            continue
        wait = 0.10 - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        subtract(conn, damage, 0, 0)
        sync(conn, 0)
        last = time.monotonic()
        os.write(1, b".")


if __name__ == "__main__":
    try:
        sys.exit(observe(sys.argv[1]) if len(sys.argv) == 2 else 1)
    except (AttributeError, BrokenPipeError, OSError):
        sys.exit(1)
