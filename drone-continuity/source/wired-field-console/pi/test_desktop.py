import collections
import hashlib
import random
import struct
import time
import unittest
from pathlib import Path
from PIL import Image
from desktop_source import FrameWorker, OwnerDesktop, Pattern, capability_valid
from display_model import Gesture, Viewport, fit_frame, patches, synthetic_frame
from wired_desktop import Link, serve


class MockSerial:
    """Model the USB queue, independent LCD operations and edge-triggered touches."""
    def __init__(self):
        self.buffer = bytearray()
        self.image = Image.new("LA", (480, 296))
        self.pen = False
        self.complete = False
        self.ended = False
        self.red_seen = self.green_seen = False
        self.puts = 0

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, size):
        if not self.buffer: time.sleep(.0003)
        count = min(size, 4)  # fragmented USB reads
        out = self.buffer[:count]
        del self.buffer[:count]
        return out

    def line(self, value):
        self.buffer.extend((value + "\n").encode("ascii"))

    def write(self, data):
        cmd = data.decode("ascii").strip().split()
        if cmd[0] == "HELLO": self.line("DESKTOP XIAO 1")
        elif cmd[0] == "BEGIN": self.line("READY")
        elif cmd[0] == "PING": self.line("PONG")
        elif cmd[0] == "END": self.ended = True; self.line("ENDED")
        elif cmd[0] == "PUT":
            seq, p = cmd[1], bytes.fromhex(cmd[2])
            self.puts += 1
            if self.puts == 1:
                self.line("ERROR SEQUENCE")
                return len(data)
            if self.puts == 3:
                self.line("BUSY")
                return len(data)
            self.line("QUEUED " + seq)
            if p[0] == 1:
                x, y, w, h, color = struct.unpack(">5H", p[1:])
                self.image.paste((color >> 8, color & 255), (x,y,x+w,y+h))
            elif p[0] == 2:
                x, y, count = struct.unpack(">HHB", p[1:6])
                self.image.paste(Image.frombytes("LA", (count,1), p[6:]), (x, y))
            elif p[0] == 3:
                self.image.paste((0,0), (0,0,480,296))
            elif p[0] != 4:
                raise AssertionError("Bad payload")
            if p[0] == 4 and self.image.getpixel((120,90)) == (0xda, 0x24) and not self.pen:
                self.line("TOUCH 30 1 120 90")
                self.line("TOUCH 30 1 120 90")
                self.line("TOUCH 31 2 120 90")
                self.pen = True
            pixel = self.image.getpixel((120,90))
            self.red_seen |= pixel == (0xda,0x24)
            self.green_seen |= pixel == (0x06,0x6c)
            self.line("ACK " + seq)
        else:
            raise AssertionError("Unexpected command")
        return len(data)


class DesktopTests(unittest.TestCase):
    def test_pixels(self):
        for color in ("red", "white", "black", "blue", (9, 16, 224)):
            image = Image.new("RGB", (480,296), color)
            frame, _ = fit_frame(image)
            r,g,b = image.getpixel((1,1))
            self.assertEqual(bytes(frame.getpixel((1,1))), struct.pack(">H", ((r>>3)<<11)|((g>>2)<<5)|(b>>3)))
        original = synthetic_frame()
        rng = random.Random(40)
        for _ in range(120):
            original.putpixel((rng.randrange(480),rng.randrange(296)), (rng.randrange(256), 16, 125))
        goal, _ = fit_frame(original)
        current = Image.new("LA",(480,296))
        for _, patch in patches(current, goal):
            self.assertLessEqual(len(patch.packet),62)
            patch.apply(current)
        self.assertEqual(current.tobytes(), goal.tobytes())
        self.assertEqual(list(patches(current, goal)), [])

    def test_touch(self):
        _, view = fit_frame(Image.new("RGB",(800,600)))
        self.assertEqual(view.point(view.x,view.y), (0,0))
        self.assertEqual(view.point(view.x+view.w-1,view.y+view.h-1), (10000,10000))
        self.assertIsNone(view.point(0,0))
        g = Gesture()
        g.feed(1, 0, 5, view)
        self.assertIsNone(g.feed(2, 80, 70, view))
        g.feed(1, 70, 70, view)
        self.assertEqual(g.feed(2, 77, 100, view)["type"], "drag")
        self.assertIsNone(g.feed(2, 77, 100, view))

    def test_capability(self):
        fake = "a" * 64
        cfg = {"expires_unix":200,"token_sha256":hashlib.sha256(fake.encode()).hexdigest()}
        self.assertTrue(capability_valid(fake, cfg, 100))
        self.assertTrue(capability_valid("https://example.invalid/#"+fake, cfg, 100))
        self.assertFalse(capability_valid(fake, cfg, 200))
        self.assertFalse(capability_valid("b"*64, cfg, 100))

    def test_disconnect(self):
        link = MockSerial()
        transport = Link(link, lambda *_: None, lambda: None)
        link.line("LOST")
        with self.assertRaises(RuntimeError):
            transport.next_line(time.monotonic() + 0.3)

    def test_revoked_owner(self):
        class Denied(Pattern):
            def open(self):
                raise PermissionError("locked")
            def frame(self):
                raise AssertionError("A denied user may not capture the desktop")
        worker = FrameWorker(Denied())
        worker.thread.start()
        self.assertTrue(worker.ready.wait(1))
        with self.assertRaises(RuntimeError):
            worker.snapshot()
        self.assertEqual(worker.frame_id, 0)
        worker.thread.join(1)

    def test_bad_frame_identity(self):
        source = OwnerDesktop.__new__(OwnerDesktop)
        source.base = ""
        source.call = lambda *args, **kwargs: {"jpeg":"AA==", "frame_id":"0"*64}
        with self.assertRaises(ValueError):
            source.frame()

    def test_complete_synthetic_session(self):
        channel = MockSerial()
        worker = FrameWorker(Pattern())
        worker.thread.start()
        self.assertTrue(worker.ready.wait(2))
        serve(channel, worker, 2.5)
        worker.thread.join(1)
        self.assertTrue(channel.red_seen and channel.green_seen and channel.ended)
        self.assertEqual(channel.image.getextrema(), ((0,0), (0,0)))


if __name__ == "__main__":
    unittest.main()
