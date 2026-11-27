import base64
import ctypes as C
import hashlib
import io
import os
import secrets
import select
import shutil
import struct
import subprocess
import threading
import time
import unittest
import zlib
from dataclasses import replace
from unittest.mock import patch

from PIL import Image
from desktop_source import OwnerDesktop
from display_damage import DamageWake
from display_model import HEIGHT, WIDTH, POINTER_RANGE, Zoom, fit_frame
from wired_desktop import serve


def position(x, y, w=WIDTH, h=HEIGHT):
    return round(x*POINTER_RANGE / (w-1)), round(y*POINTER_RANGE / (h-1))


def desktop_fixture(width=800, height=450):
    image = Image.new("RGB", (width, height), (24, 52, 65))
    blob = io.BytesIO()
    image.save(blob, "JPEG", quality=80)
    raw = blob.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    encoded = base64.b64encode(raw).decode("ascii")
    def broker(action, base):
        if base == digest:
            return {"frame_id": digest}
        return {"frame_id": digest, "jpeg": encoded, "width": width, "height": height}
    with patch("os.getuid", return_value=1000):
        source = OwnerDesktop()
    source.call = broker
    return source


class PointerTests(unittest.TestCase):
    def test_guard_letterbox_edges_and_zoom(self):
        source = desktop_fixture()
        class Watch:
            position = (0, 0)
        source.pointer_watcher = Watch()
        frame, view = source.frame()
        zoom = Zoom()
        marked, first = zoom.project(frame, view)
        self.assertEqual(first.pointer_box[:2], (0, 13))
        self.assertNotEqual(marked.tobytes(), frame.tobytes())
        self.assertEqual(marked.crop((0, 0, 480, 13)).tobytes(), frame.crop((0, 0, 480, 13)).tobytes())
        self.assertIsNone(source.frame())
        Watch.position = (POINTER_RANGE, POINTER_RANGE)
        next_frame, view = source.frame()
        self.assertIs(next_frame, frame)
        moved, edge = zoom.project(next_frame, view)
        self.assertEqual(edge.pointer_box[2:], (480, 283))
        self.assertEqual(moved.crop(first.pointer_box).tobytes(), frame.crop(first.pointer_box).tobytes())
        zoom.command(1)
        offscreen, clean_zoom = zoom.project(next_frame, view)
        self.assertIsNone(clean_zoom.pointer_box)
        for _ in range(2):
            zoom.command(4)
            zoom.command(6)
        zoomed, area = zoom.project(next_frame, view)
        self.assertEqual(area.pointer_box[2:], (480, 283))
        self.assertNotEqual(zoomed.tobytes(), offscreen.tobytes())
        Watch.position = None
        reverted, clean = source.frame()
        self.assertIs(reverted, frame)
        self.assertIsNone(zoom.project(reverted, clean)[1].pointer_box)
        Watch.position = (123, 456)
        def deny(*args, **kwargs): raise PermissionError("revoked")
        source.call = deny
        with self.assertRaises(PermissionError):
            source.frame()

    def test_continually_moving_source_commits_full_positions(self):
        base, view = fit_frame(Image.new("RGB", (WIDTH,HEIGHT), "black"), native=True)
        class Source: pass
        class Worker:
            source = Source()
            stop = threading.Event()
            index = 0
            def snapshot(self):
                ordinal = self.index
                point = position(12 + (ordinal*71) % 430, 14 + (ordinal*83) % 250)
                return ordinal, base, replace(view, pointer=point)
        worker = Worker()
        live = [False]
        canvas = Image.new("LA", (WIDTH, HEIGHT))
        # Replay real zlib headers/fragments at the receiver and change the source
        # during each transfer. Commits are sampled before input stops moving.
        class Link:
            capabilities=5
            owns_final_clear=True
            active=True
            graphics_burst=8
            def __init__(self,*args): pass
            def begin(self): pass
            def end(self): pass
            def send(self, packet):
                if packet[0] == 6:
                    self.x,self.y,self.w,self.h,self.size = struct.unpack(">5H",packet[1:])
                    self.buf=bytearray()
                elif packet[0] == 7:
                    self.buf.extend(packet[3:])
                    if len(self.buf) == self.size:
                        canvas.paste(Image.frombytes("LA",(self.w,self.h),zlib.decompress(self.buf)),
                                     (self.x,self.y))
                elif packet[0] == 1:
                    x,y,w,h=struct.unpack(">4H",packet[1:9])
                    canvas.paste(tuple(packet[9:]),(x,y,x+w,y+h))
                elif packet[0] == 2:
                    x,y,w=struct.unpack(">HHB",packet[1:6])
                    canvas.paste(Image.frombytes("LA",(w,1),packet[6:]),(x,y))
                if live[0]:
                    worker.index += 1
                time.sleep(.001)
            def send_graphics(self, packets):
                for packet in packets: self.send(packet)
            def next_line(self, deadline):
                if live[0]: worker.index += 1
                time.sleep(.001)
        paints, moves = [], []
        def notice(name, value):
            if name == "paint":
                point = position(12 + (value*71) % 430, 14 + (value*83) % 250)
                target,_ = Zoom().project(base,replace(view,pointer=point))
                self.assertEqual(canvas.tobytes(),target.tobytes())
                paints.append(value)
                if not live[0]:
                    live[0]=True
                    worker.index+=1
            elif name == "pointer-commit":
                self.assertGreaterEqual(value,0)
                moves.append(value)
        serve(None,worker,.4,link_factory=Link,notice=notice,direct_usb=True)
        self.assertGreaterEqual(len(moves),3)
        self.assertEqual(len(set(paints)),len(paints))
        self.assertGreater(worker.index, len(paints)*2)

    @unittest.skipUnless(shutil.which("Xvfb"), "isolated Xvfb unavailable")
    def test_virtual_x11_mouse_wakes_static_drawable(self):
        # Select an isolated high display and require its own readiness receipt.
        number = str(18000 + secrets.randbelow(12000))
        xvfb = subprocess.Popen(["Xvfb", ":"+number, "-displayfd", "1", "-nolisten", "tcp",
                                 "-screen", "0", "800x450x24"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        watch = conn = None
        try:
            self.assertTrue(select.select([xvfb.stdout], [], [], 4)[0])
            self.assertEqual(xvfb.stdout.readline().strip(), number.encode())
            x = C.CDLL("libX11.so.6")
            x.XOpenDisplay.argtypes=[C.c_char_p]; x.XOpenDisplay.restype=C.c_void_p
            x.XDefaultRootWindow.argtypes=[C.c_void_p]; x.XDefaultRootWindow.restype=C.c_ulong
            x.XWarpPointer.argtypes=[C.c_void_p,C.c_ulong,C.c_ulong,C.c_int,C.c_int,
                                     C.c_uint,C.c_uint,C.c_int,C.c_int]
            x.XSync.argtypes=[C.c_void_p,C.c_int]
            x.XCloseDisplay.argtypes=[C.c_void_p]
            conn = x.XOpenDisplay((":"+number).encode())
            self.assertTrue(conn)
            root=x.XDefaultRootWindow(conn)
            event = threading.Event()
            watch = DamageWake(event, ":"+number)
            source = desktop_fixture()
            source.pointer_watcher = watch
            self.assertTrue(event.wait(2))
            source.frame()
            for px,py in ((41,31),(395,227),(795,446),(49,44)):
                event.clear()
                x.XWarpPointer(conn,0,root,0,0,0,0,px,py)
                x.XSync(conn,0)
                deadline=time.monotonic()+.35
                while watch.position != position(px,py,800,450) and time.monotonic()<deadline:
                    event.wait(.01)
                    event.clear()
                self.assertEqual(watch.position,position(px,py,800,450))
                clean, view = source.frame()
                painted, area = Zoom().project(clean,view)
                self.assertIsNotNone(area.pointer_box)
                self.assertNotEqual(painted.tobytes(),clean.tobytes())
                self.assertIsNone(source.frame())
        finally:
            if watch: watch.close()
            if conn: x.XCloseDisplay(conn)
            xvfb.terminate()
            xvfb.wait(2)
            xvfb.stdout.close()
