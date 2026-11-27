"""Exercise a negotiated portrait session without an enrolled device or X11 desktop."""
import base64
import hashlib
import io
import queue
import secrets
import struct
import threading
import unittest
from dataclasses import replace
from types import SimpleNamespace

from PIL import Image
from desktop_source import OwnerDesktop
from display_model import (LANDSCAPE, PORTRAIT, POINTER_RANGE, Gesture, Zoom,
                           desktop_updates, fit_frame, synthetic_frame, with_pointer)
from paired_wire import LinkEnded, authenticate
from scene_codec import jpeg_scene, zlib_updates
from test_pair_service import TestWire
from wired_desktop import serve


class PortraitTests(unittest.TestCase):
    def test_capability_select_ack_and_touch_bounds(self):
        class Wire(TestWire):
            advertised = 0
            def send(self, data, seconds=3):
                if data[0] == 0x63:
                    clear = self.d.decrypt(self.keys[64:72]+data[1:5],data[5:],data[:5])
                    self.last_clear = clear
                    if clear == b'\x03':
                        self.send_up(bytes([0x25,1,self.advertised])+data[1:5])
                        return
                return super().send(data,seconds)
        key=secrets.token_bytes(32)
        wire=Wire(key)
        session=authenticate(wire,key)
        self.assertEqual(session.preferred_surface(),LANDSCAPE)
        with self.assertRaises(LinkEnded):session.select_portrait()
        wire.advertised=0x40
        self.assertEqual(session.preferred_surface(),PORTRAIT)
        self.assertEqual(session.surface,LANDSCAPE)
        wire.valid_ack=False
        with self.assertRaises(LinkEnded):session.select_portrait()
        self.assertEqual(session.surface,LANDSCAPE)
        wire.valid_ack=True
        session.select_portrait()
        self.assertEqual(wire.last_clear,b'\x12V\x01@\x01\xc8')
        accepted=[]
        session.touch=lambda *data:accepted.append(data)
        def contact(x,y):
            wire.send_up(struct.pack('>BHBHHI',0x22,4,2,x,y,session.ack))
        contact(319,455)
        self.assertEqual(accepted,[(2,319,455)])
        for pair in [(320,0),(0,456)]:
            with self.assertRaises(LinkEnded):contact(*pair)

    def test_projection_touches_zoom_and_pointer_hotspot(self):
        raw=Image.new('RGB',(640,912),'#954')
        frame,view=fit_frame(raw,native=True,surface=PORTRAIT)
        self.assertEqual((view.x,view.y,view.w,view.h),(0,0,320,456))
        for x in [0,159,319]:
            for y in [0,227,455]:
                nx,ny=view.point(x,y)
                self.assertLessEqual(abs(round(nx*639/10000)-x*639/319),.51)
                self.assertLessEqual(abs(round(ny*911/10000)-y*911/455),.51)
                ptr=tuple(round(n*POINTER_RANGE/10000) for n in (nx,ny))
                _,cursor=with_pointer(frame,view,ptr)
                box=cursor.pointer_box
                self.assertEqual(x,box[2]-1 if x==319 else box[0])
                self.assertEqual(y,box[3]-1 if y==455 else box[1])
                gesture=Gesture()
                gesture.feed(1,x,y,view)
                self.assertEqual(gesture.feed(2,x,y,view),{'type':'tap','button':'left','x':nx,'y':ny})
        zoom=Zoom()
        for action in [2,4,4,4,4,6,6,6,6]:zoom.command(action)
        enlarged,window=zoom.project(frame,replace(view,pointer=(POINTER_RANGE,POINTER_RANGE)))
        self.assertEqual(enlarged.size,PORTRAIT)
        self.assertEqual(window.point(319,455),(10000,10000))
        self.assertEqual(window.pointer_box[2:],PORTRAIT)
        self.assertIsNone(window.point(0,456))

    def test_picture_and_exact_sparse_updates_reach_bottom_row(self):
        current=Image.new('LA',PORTRAIT)
        target=current.copy()
        for x,y in [(0,0),(319,0),(0,455),(319,455),(100,411),(101,412)]:
            target.putpixel((x,y),(255,253))
        for planner in [desktop_updates,zlib_updates]:
            replay=current.copy()
            for _,item in planner(replay,target):
                x,y,w,h=item.rect
                self.assertTrue(0<=x<x+w<=320 and 0<=y<y+h<=456)
                item.apply(replay)
            self.assertEqual(replay.tobytes(),target.tobytes())
        scene=jpeg_scene(target)
        self.assertEqual(scene.rect,(0,0,*PORTRAIT))
        _,_,w,h,_=struct.unpack('>BHHHI',scene.packets[0])
        self.assertEqual((w,h),PORTRAIT)
        blob=b''.join(p[3:] for p in scene.packets[1:-1])
        self.assertEqual(Image.open(io.BytesIO(blob)).size,PORTRAIT)

    def test_paired_source_uses_portrait_capture_and_checks_bounded_image(self):
        source=OwnerDesktop.__new__(OwnerDesktop)
        source.base=''
        source.surface=PORTRAIT
        source.pointer_watcher=None
        def reply(size):
            sample=io.BytesIO()
            Image.new('RGB',size,'#076').save(sample,'PNG')
            raw=sample.getvalue()
            def call(action,**options):
                self.assertEqual((action,options),('frame',{'base':source.base,'lossless':True,'portrait':True}))
                return dict(frame_id=hashlib.sha256(raw).hexdigest(),width=size[0],height=size[1],
                            png=base64.b64encode(raw).decode())
            return call
        source.call=reply((640,912))
        frame,area=source.frame()
        self.assertEqual((frame.size,area.native.size),(PORTRAIT,(640,912)))
        source.call=reply((641,912))
        with self.assertRaises(ValueError):source.frame()

    def test_guarded_serve_selects_before_graphics_and_invalidates_lower_portrait(self):
        source=SimpleNamespace(surface=PORTRAIT)
        frame,view=fit_frame(synthetic_frame(surface=PORTRAIT),surface=PORTRAIT,native=True)
        worker=SimpleNamespace(source=source,commands=queue.Queue(),stop=threading.Event(),
                               snapshot=lambda:(1,frame,view))
        sent=[]
        selected=[]
        class Peer:
            active=True
            owns_final_clear=True
            capabilities=0x40
            def __init__(self,serial,touch,health):self.touch=touch
            def begin(self):pass
            def end(self):pass
            def select_portrait(self):selected.append(list(sent))
            def send(self,payload,**kwargs):sent.append(payload)
            def next_line(self,deadline):pass
        peer=None
        def create(*args):
            nonlocal peer
            peer=Peer(*args)
            return peer
        class Completed(Exception):pass
        paints=[]
        def event(name,value):
            if name=='paint':
                paints.append(value)
                if len(paints)==1:
                    peer.touch(1,319,455)
                    peer.touch(2,319,455)
                    self.assertTrue(peer.control(0x26,1,None))
                else:raise Completed()
        with self.assertRaises(Completed):
            serve(None,worker,1,link_factory=create,notice=event)
        self.assertEqual(selected,[[b'\x04']])
        self.assertEqual(worker.commands.get_nowait()['y'],10000)
        self.assertIn(struct.pack('>B5H',1,0,312,320,144,0),sent)


if __name__=='__main__':
    unittest.main()
