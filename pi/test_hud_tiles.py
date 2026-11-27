"""Fixed synthetic HUD glyphs at their projected 480×296 positions."""
import base64
import unittest
import zlib
from PIL import Image
from scene_codec import ObjectUpdate, direct_cost, exchanges, interactive_plan, select_plan
from test_direct_scene_plans import replay
from test_interactive_paints import Receiver, Worker, white_box
from display_model import Zoom
from wired_desktop import serve

# Each compressed fixture holds target RGB565 pixels followed by its 1-bit change mask.
# Rendered from synthetic 800×600 CPU/state/pin labels, independent of host fonts.
CASES = (
    ('temperature', (87, 3, 97, 15), (2, 2),
     'eNqzem903mgdEJ63grDOG62XfK2kA6KVeCRPK/kavdfKNdJqMfDKUtLRfFW8fkph0BslbivvHoNgPqseyZVzNvUU'
     'eZ25VmmVbZVd/V7zpZKulnZxrxY3o8bakOILgpnJvsfEgTp4tLSVfK2yj4kbcRmdV9KJ1j36XfGU0QfNk8fEo96A'
     '7Tvv1H1MXHKl4sq1Jl6rOT0h7tq7LdlPUO1cxN7vQWeKPxhxavUZrXfKBprGlewbrZucl+xr+BIkBsRA9Uq6EAgS'
     'AepeD/EZFIJ5fAz6DPYNtQfqD5g2/GeQb/gPZMk3yDIAAK1maRo='
    ),
    ('state', (104, 3, 129, 17), (4, 3),
     'eNozWmd0HgjXQeF5OFyHE57X8lXihqnQfKV5Uolb86SWNm49WnlOWcm6StxWH4zOS/Fk9y0VYVhyTtxIy2g90Kz1'
     'WusxdUrpZK/fe01wlZaOlbcRZ3be2jKGo9dmgnQovrbytvJWfI2uR0k3OW9tKcOzGoG1Jj0B12bNFeE4eq3Sylvy'
     'VIvBUpO1odXvJV+h6lHyBbrERLP9XKXiSU6PpaZAO5Zem6l4Mlp36zSGo4JsR787dWv1oeuYczlo1dpSyVNa/dkg'
     '+0A6OmoEz0W2GPQUbt0WdEYrF9kWJV2gjs9WmuciBDM4M3uKgDqArpJ0L76wdaqku+aJbB/NFcBQQLZDJ7tv73WG'
     'JVunzrmc7XtvF1BHy7PfybqS7mtDagRaApd8VjyF6g+gGzmdspR0NF8l+0bzGr5w8lI85bXGq1uJW4sLJKJ4EqgK'
     'xQ6j9Vp9YHeeV9JV8gWy84DxkAsWWQ8SAdEYsQiLpfNg2fNGiHSDP7XQENp+YGCw/8HA8P93PsP//+8a1v//31D/'
     '/z9DHRD///8Pju3f/2GIf/SHgYGhAogVGAAlFkmX'
    ),
    ('pin', (60, 3, 135, 15), (9, 5),
     'eNqdVUFo21YYVrayxY5NZGZolO4iHdroNYZYy2FTDwUNtkypwuIRCHFvDt0WYUNicggxSw+GJI1wmXEDA41d5i52'
     'Zgs83ENYaC/OZjtEB4MH28h6aUNsBwfMMKMw73+S4zgdPWx6IH3v6b3vffrf/39CtzidS/N13DCCprefZtMu9P5L'
     '0zuMBu7s0Y1fsRYZqqgqboN9WAOSmOHOfA1FUOB/6aozElVAEWBMY05zB6rIDHfjVzGjW/wpXQhGlMkwGSI5K+MS'
     't702RuJOgVFHER7xCHo6xkbctDY2I3o2iiOsGaOaGRuq4LXHouyx8Z0Bvjc8EibDpDIvzrkfAu438D3GZfC0+Tqs'
     'oOoG6VgvLwVPBTmo55r0Ft/rScJXWoUNtmIZUxayi/QqitAFQUZW5EfD7BadEDboPPJzGh7lEF3lTxkbZxVkunKm'
     'SRnJLtZvCxvGThHuungybhfE8o7XTuc/sYsnwtzhr+I+nEOEzdNrvMxWqALeEVh1UxW1vlsWNpgJy+dqKUR6ttUS'
     'fSc1FYuCxkupqfKO8BG1Fh+NZbKLsG7rcCc2D/gBZ6XzaiaWSU0FdcdnPim7qDbUBp3H0aGr4nbvM2D9HlTh3IQ4'
     'UjWvPf4WtY5PwVGUA2rGkYC9C7Ev9waUj3fLy3U1ulvmRRx9U1Wu6TlBEUaS76uNmaLa8CTLO8T7nqT7ZzmilnqG'
     'BFmWCF/cqSw4rja/FveJ59lHPpccSE1ZhrhxNcPe2XuX3SJm486gbmYLqCjsXW6rMvKMTuyWxW2IDsSSzuea/Djk'
     'R92RjDvjU8RsdjO1ScymNpdPB21wlh1VnAaqNLXkScL7cCy6+0swTeTCbrVBVdl8uF+ZPFgKu6lPy0t0harFnTPV'
     'WEbWGNiF2BPmjt4Ojyjz8dFlnekzqvqUSrRVGbk4aAtq3zaoJNSeTlXDZCxKFXAdOpJqI+TuGYo7Q2TPEGCyowq+'
     'QpCpmmMs+8hT87niTnaV/Y58tjcgByDSDeKhEk0tEq+pJWWB+vBgGvVRxbjTawMd0Z4hZPVJ7p/KX0G+rflsfC+S'
     'zlTlmqDKzx4jK0QnYUYHnyd7nGtyVlwXfJ0qqKWwu+dNUOW+qMqxfjAd+8E3AXmRsVwLkXHne0cHS5ApmzM1z/bz'
     'F+7VmdregM91+JsSpT443EFWRzE1GiLp1YPLQV1tKPOWN2LRWEnWsg94ZLoBqFovT4snjrFcGXa9Bu+N6OBKwDqo'
     'IuC0eYLKAnGUmgpPgrZReFPFqqB++sQ534RP8tRo7DAWYY5KQCYFxG2mD/V57bjv2ffaeZZHdEK8h66jgCCCY9g4'
     'JAc8+3QBYlHx2nwTUKXSmRdjVoSQJG4ICl2BVVbTu6ASMG7PQhKwisywwYfvFjPbDafxMy7GZVQluAY865D7LsM/'
     'dUaCZ53x4ydeAe5leJDhZ2lY5zf9ipHAfbr/BDq8wfv68UxYlW57mcnQmdVm6rqfebvpZW1Gk1k7d0TzGzsz9K7R'
     '7v+T/i+n1i+sf3n8vKe9dE9fCf3+1+Hr/X8TxJWVP1qt/sctglhpwfXN41br7hcYwXDrCR5r4t7Tlnn92UEwttxB'
     'K+doxVj7ovX0BsCV+ys/tp4MTNy8efXSO6T/7j+yt1mo'
    ),
)


def fixture(box, encoded):
    left,top,right,bottom=box
    size=right-left,bottom-top
    count=size[0]*size[1]*2
    data=zlib.decompress(base64.b64decode(encoded,validate=True))
    label=Image.frombytes("LA",size,data[:count])
    mask=Image.frombytes("1",size,data[count:])
    target=Image.new("LA",(480,296),(35,41))
    target.paste(label,(left,top))
    prior=target.copy()
    hi,lo=label.split()
    # Only pixel equality drives the exact-tile planner; flip one bit at each
    # stored change and preserve the real glyph in the target.
    prior.paste(Image.merge("LA",(hi,lo.point([i^1 for i in range(256)]))),(left,top),mask)
    return prior,target


class HudTiles(unittest.TestCase):
    def test_cursor_ack_in_mixed_content_precedes_rest_of_frame(self):
        worker=Worker()
        peer=Receiver(self,worker,lambda *_:None)
        notices=[]
        class Complete(Exception):pass
        def observe(kind,value):
            if kind=="paint" and value==0:
                worker.ident=1  # one real background change and a different pointer
                notices.append("first")
            elif kind=="pointer-commit":
                _,frame,view=worker.snapshot()
                self.assertEqual(white_box(peer.canvas),white_box(Zoom().project(frame,view)[0]))
                notices.append("pointer")
            elif kind=="first-feedback-ack":
                notices.append("content")
            elif kind=="paint" and value==1:
                raise Complete
        with self.assertRaises(Complete):
            serve(None,worker,4.,link_factory=peer.start,notice=observe,direct_usb=True)
        self.assertEqual(notices,["first","pointer","content"])

    def test_projected_temperature_state_and_pin(self):
        for name,box,(original,wanted),encoded in CASES:
            with self.subTest(label=name):
                before,after=fixture(box,encoded)
                stock=select_plan(before,after,0,False,31,direct_usb=True)
                self.assertEqual(exchanges(stock,8),original)
                chosen=interactive_plan(before,after,stock,(215,180),8)
                self.assertEqual(exchanges(chosen,8),wanted)
                self.assertLessEqual(direct_cost(chosen)[1],direct_cost(stock)[1])
                self.assertEqual(replay(before,chosen).tobytes(),after.tobytes())
                # The changed-area rule keeps the current content exactly intact
                # up to the tile commit. There is no early erase or empty frame.
                self.assertTrue(all(p.kind!="jpeg" for _,p in chosen if isinstance(p,ObjectUpdate)))
                legacy=interactive_plan(before,after,stock,(215,180),1)
                self.assertEqual(exchanges(legacy,1),exchanges(stock,1))

    def test_sparse_changed_pixels_keep_compact_existing_plan(self):
        before=Image.effect_noise((480,296),75).convert("LA")
        after=before.copy()
        after.putpixel((74,15),(14,15))
        after.putpixel((120,38),(17,19))
        stock=select_plan(before,after,0,False,31,direct_usb=True)
        chosen=interactive_plan(before,after,stock,(74,15),8)
        self.assertEqual(exchanges(chosen,8),2)
        self.assertEqual(direct_cost(chosen),direct_cost(stock))
        self.assertEqual(replay(before,chosen).tobytes(),after.tobytes())
