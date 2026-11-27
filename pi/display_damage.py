"""Wake guarded local capture for drawing and the current pointer hotspot."""
import ctypes as C
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import sys
import threading
import time

_POSITION = struct.Struct("!HH")
_ABSENT = 65535
_RANGE = _ABSENT - 1


class DamageWake:
    def __init__(self, activity, display=":0"):
        self.activity = activity
        self.position = None
        self.child = subprocess.Popen(
            [sys.executable, "-I", "-B", str(Path(__file__).resolve()), display],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, bufsize=0)
        self.reader = threading.Thread(target=self._receive, daemon=True)
        self.reader.start()

    def _receive(self):
        while True:
            record = bytearray()
            while len(record) < _POSITION.size:
                chunk = self.child.stdout.read(_POSITION.size - len(record))
                if not chunk:
                    if self.position is not None:
                        self.position = None
                        self.activity.set()
                    return
                record.extend(chunk)
            x, y = _POSITION.unpack(record)
            self.position = None if _ABSENT in (x, y) else (x, y)
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
    uint = C.c_uint
    uint_ptr, xid_ptr = C.POINTER(uint), C.POINTER(xid)
    open_display = bind(x, "XOpenDisplay", ptr, C.c_char_p)
    root = bind(x, "XDefaultRootWindow", xid, ptr)
    next_event = bind(x, "XNextEvent", integer, ptr, ptr)
    pending = bind(x, "XPending", integer, ptr)
    socket_fd = bind(x, "XConnectionNumber", integer, ptr)
    select_input = bind(x, "XSelectInput", integer, ptr, xid, C.c_long)
    geometry = bind(x, "XGetGeometry", integer, ptr, xid, xid_ptr, int_ptr, int_ptr,
                    uint_ptr, uint_ptr, uint_ptr, uint_ptr)
    query = bind(x, "XQueryPointer", integer, ptr, xid, xid_ptr, xid_ptr, int_ptr, int_ptr,
                 int_ptr, int_ptr, uint_ptr)
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
    root_window = root(conn)
    # Observe root resizes and accumulated drawable damage. Button and key events
    # are never selected. Only normalized pointer position leaves this child.
    select_input(conn, root_window, 1 << 17)  # StructureNotifyMask
    damage = create(conn, root_window, 3)
    if not damage:
        return 1
    sync(conn, 0)
    event = (C.c_long * 24)()
    fd = socket_fd(conn)
    unused_root, unused_child = xid(), xid()
    px, py, ignored_x, ignored_y = (integer() for _ in range(4))
    width, height, depth, border, ignored_mask = (uint() for _ in range(5))
    resized = True
    dirty = False
    previous = None
    next_pointer = next_damage = 0.0
    while True:
        while pending(conn):
            next_event(conn, C.byref(event))
            event_type = C.cast(event, int_ptr)[0]
            if event_type == base.value:
                dirty = True
            elif event_type == 22:  # ConfigureNotify
                resized = True
        now = time.monotonic()
        if resized:
            if not geometry(conn, root_window, C.byref(unused_root), C.byref(ignored_x),
                            C.byref(ignored_y), C.byref(width), C.byref(height),
                            C.byref(border), C.byref(depth)):
                return 1
            resized = False
            next_pointer = 0.0
        wake = dirty and now >= next_damage
        if wake:
            subtract(conn, damage, 0, 0)
            sync(conn, 0)
            dirty = False
            next_damage = now + .10
        if now >= next_pointer:
            same_screen = query(conn, root_window, C.byref(unused_root), C.byref(unused_child),
                                C.byref(px), C.byref(py), C.byref(ignored_x), C.byref(ignored_y),
                                C.byref(ignored_mask))
            position = (_ABSENT, _ABSENT)
            if same_screen and 0 <= px.value < width.value and 0 <= py.value < height.value:
                position = (round(px.value * _RANGE / max(1, width.value-1)),
                            round(py.value * _RANGE / max(1, height.value-1)))
            wake = wake or position != previous
            previous = position
            next_pointer = now + 1/30
        if wake:
            os.write(1, _POSITION.pack(*previous))
        soonest = min(next_pointer, next_damage) if dirty else next_pointer
        select.select([fd], [], [], max(0, soonest - time.monotonic()))


if __name__ == "__main__":
    try:
        sys.exit(observe(sys.argv[1]) if len(sys.argv) == 2 else 1)
    except (AttributeError, BrokenPipeError, OSError):
        sys.exit(1)
