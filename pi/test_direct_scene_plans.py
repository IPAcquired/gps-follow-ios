"""Exercise the direct route against the R3.3 scene protocol and its ESP32 limits."""
import json
import random
import struct
import unittest
import zlib

from PIL import Image, ImageDraw

from display_model import HEIGHT, WIDTH, rgb565
from scene_codec import direct_cost, select_plan, zlib_updates


def records(plan):
    return [p for _, item in plan for p in
            (item.packets if hasattr(item, "packets") else (item.packet,))]


def replay(canvas, plan):
    canvas = canvas.copy()
    for _, item in plan:
        packets = item.packets if hasattr(item, "packets") else (item.packet,)
        header = packets[0]
        if header[0] == 1:
            _, x, y, w, h = struct.unpack(">B4H", header[:9])
            canvas.paste(tuple(header[9:]), (x,y,x+w,y+h))
        elif header[0] == 2:
            _, x, y, w = struct.unpack(">BHHB", header[:6])
            canvas.paste(Image.frombytes("LA", (w,1), header[6:]), (x,y))
        elif header[0] == 6:
            _, x, y, w, h, size = struct.unpack(">B5H", header)
            assert 0 < w*h <= 2048 and 0 < size <= 4128
            assert x+w <= WIDTH and y+h <= HEIGHT
            data = bytearray()
            for packet in packets[1:]:
                assert struct.unpack(">BH", packet[:3]) == (7,len(data))
                assert 4 <= len(packet) <= 40
                data.extend(packet[3:])
            assert len(data) == size
            raw = zlib.decompress(bytes(data))
            assert len(raw) == w*h*2
            canvas.paste(Image.frombytes("LA", (w,h), raw), (x,y))
        else:
            raise AssertionError("Expected an exact R3.3 record")
    return canvas


class DirectScenes(unittest.TestCase):
    def setUp(self):
        image = Image.new("RGB", (WIDTH, HEIGHT), "#233a5a")
        d = ImageDraw.Draw(image)
        for i in range(12):
            d.text((4,6+i*22), "Documents    File manager   Settings", fill="white")
        self.before = rgb565(image)
        d.rectangle((19,31,403,257), fill="#dfe6ef", outline="black", width=2)
        for i in range(8):
            d.text((30,42+i*23), "Settings    Display    Keyboard", fill="#182640")
        self.after = rgb565(image)

    def test_menu_bytes_records_and_complete_exact_pixels(self):
        base = select_plan(self.before,self.after,0,False,31)
        chosen = select_plan(self.before,self.after,0,False,31,direct_usb=True)
        self.assertEqual(records(base)[0][0], 9)
        self.assertLess(direct_cost(chosen)[0], direct_cost(base)[0])
        self.assertLessEqual(direct_cost(chosen)[1]*5, direct_cost(base)[1]*4)
        self.assertEqual(replay(self.before,chosen).tobytes(), self.after.tobytes())
        envelope_bytes = []
        for packet in records(chosen):
            message = {"action":"wired_usb_exchange","request_id":1,"seq":1,
                       "down_hex":bytes(21+len(packet)).hex()}
            envelope_bytes.append(len((json.dumps(message,separators=(",",":"))+"\n").encode()))
        self.assertEqual(direct_cost(chosen), (len(envelope_bytes),sum(envelope_bytes)))

    def test_first_zoom_legacy_and_photo_preserve_exact_wire_sequence(self):
        rng = random.Random(31)
        photo = Image.frombytes("LA", (WIDTH,HEIGHT), rng.randbytes(2*WIDTH*HEIGHT))
        for target, initial, capability in ((self.after,True,31), (self.after,False,4),
                                             (self.after,False,0), (photo,False,31)):
            with self.subTest(initial=initial, capability=capability):
                stock = select_plan(self.before,target,2,initial,capability)
                direct = select_plan(self.before,target,2,initial,capability,direct_usb=True)
                self.assertEqual(records(direct), records(stock))

    def test_edges_thin_stripes_and_disconnected_rectangles(self):
        rng = random.Random(3)
        for x,y,w,h in ((0,0,1,1), (479,92,1,204), (4,295,476,1), (1,2,127,73), (221,71,259,225)):
            with self.subTest(width=w, height=h):
                target = self.before.copy()
                for px,py in ((x,y), (x+w-1,y+h-1)):
                    target.putpixel((px,py), (91,47))
                tw,th = max(1,w//2),max(1,h//2)
                region = Image.frombytes("LA", (tw,th), rng.randbytes(2*tw*th))
                target.paste(region, (x,y))
                plan = zlib_updates(self.before,target,(x,y,x+w,y+h))
                self.assertEqual(replay(self.before,plan).tobytes(), target.tobytes())

    def test_empty_and_single_pixel(self):
        self.assertEqual(select_plan(self.before,self.before,0,False,31,direct_usb=True), [])
        target = self.before.copy()
        target.putpixel((WIDTH-1,HEIGHT-1),(241,103))
        plan = select_plan(self.before,target,0,False,31,direct_usb=True)
        self.assertEqual(len(records(plan)), 1)
        self.assertEqual(replay(self.before,plan).tobytes(), target.tobytes())
