import io
import random
import queue
import struct
import threading
import unittest
import zlib

from PIL import Image
from display_model import HEIGHT,WIDTH,Viewport,Zoom,fit_frame,rgb565
from desktop_source import FocusRequest
from scene_codec import MAX_JPEG,jpeg_scene,select_plan,to_rgb,zlib_updates
from wired_desktop import serve


class SceneCodecTests(unittest.TestCase):
    def test_full_scene_is_bounded_baseline_and_only_final_packet_commits(self):
        size=(WIDTH,HEIGHT)
        noise=random.Random(1234).randbytes(WIDTH*HEIGHT*2)
        target=Image.frombytes("LA",size,noise)
        picture=jpeg_scene(target)
        opcode,length,width,height,check=struct.unpack(">BHHHI",picture.packets[0])
        self.assertEqual((opcode,width,height),(9,*size))
        self.assertLessEqual(length,MAX_JPEG)
        staged=bytearray()
        for packet in picture.packets[1:-1]:
            kind,offset=struct.unpack(">BH",packet[:3])
            self.assertEqual((kind,offset),(10,len(staged)))
            self.assertLessEqual(len(packet),40)
            staged.extend(packet[3:])
        self.assertEqual(picture.packets[-1],b"\x0b")
        self.assertEqual(len(staged),length)
        self.assertEqual(zlib.crc32(staged),check)
        with Image.open(io.BytesIO(staged)) as decoded:
            self.assertEqual(decoded.size,size)
            self.assertEqual(decoded.format,"JPEG")
            self.assertFalse(decoded.info.get("progressive"))
            decoded.load()

    def test_sparse_tiles_are_exact_and_leave_other_pixels_untouched(self):
        base=Image.new("LA",(WIDTH,HEIGHT))
        target=base.copy()
        generator=random.Random(7)
        target.paste(Image.frombytes("LA",(85,41),generator.randbytes(85*41*2)),(17,21))
        canvas=base.copy()
        for _,item in zlib_updates(base,target):
            kind,x,y,w,h,length=struct.unpack(">B5H",item.packets[0])
            self.assertEqual(kind,6)
            self.assertLessEqual(w*h,2048)
            staged=bytearray()
            for packet in item.packets[1:]:
                self.assertEqual(struct.unpack(">BH",packet[:3]),(7,len(staged)))
                staged.extend(packet[3:])
            self.assertEqual(len(staged),length)
            canvas.paste(Image.frombytes("LA",(w,h),zlib.decompress(staged)),(x,y))
        self.assertEqual(canvas.tobytes(),target.tobytes())
        self.assertEqual(select_plan(target,target,0,False,7),[])

    def test_rgb565_primary_colors_and_negotiated_route(self):
        src=Image.new("RGB",(5,1))
        colors=[(0,0,0),(255,255,255),(255,0,0),(0,255,0),(0,0,255)]
        src.putdata(colors)
        self.assertEqual(list(to_rgb(rgb565(src)).getdata()),colors)
        first=Image.new("LA",(WIDTH,HEIGHT))
        second=Image.new("LA",first.size,(0xf8,0))
        self.assertEqual(select_plan(first,second,0,False,4)[0][1].kind,"jpeg")
        self.assertTrue(all(hasattr(p,"packet") for _,p in select_plan(first,second,0,True,0)))

    def test_input_polls_during_jpeg_transmission_only_accept_unchanged_target(self):
        first=Image.new("LA",(WIDTH,HEIGHT),(0xf8,0));second=Image.new("LA",first.size,(7,224))
        second.paste((0xf8,0),(0,0,80,80))
        class Worker:
            source=object();stop=threading.Event();commands=queue.Queue()
            generation=1
            def snapshot(self):
                return self.generation,(first,second)[self.generation-1],Viewport(0,0,WIDTH,HEIGHT)
        worker=Worker()
        class Done(Exception):pass
        class Fake:
            capabilities=15;active=False;stimulus=False
            def __init__(self,serial,touch,health):self.touch=touch;self.health=health
            def begin(self):self.active=True
            def end(self):self.active=False
            def next_line(self,deadline):pass
            def send(self,payload,seconds=2):
                if worker.generation==2 and payload[0]==10 and not self.stimulus:
                    self.stimulus=True
                    for x,y in ((40,40),(200,160)):
                        self.touch(1,x,y);self.touch(2,x,y)
        def notice(kind,value):
            if kind=="paint":
                if worker.generation==2:raise Done()
                worker.generation=2
        with self.assertRaises(Done):serve(None,worker,link_factory=Fake,notice=notice)
        self.assertEqual(worker.commands.qsize(),1)
        self.assertEqual(worker.commands.get()["x"],round(40*10000/(WIDTH-1)))

    def test_native_zoom_letterboxing_pan_edges_and_reset(self):
        base,normal=fit_frame(Image.new("RGB",(960,720)),native=True)
        zoom=Zoom();zoom.command(1)
        _,center=zoom.project(base,normal)
        self.assertEqual(center.source_box,(240,180,480,360,960,720))
        self.assertIsNone(center.point(0,100))
        self.assertEqual(center.point(center.x,center.y),(round(240e4/959),round(180e4/719)))
        for action in [3,5]*9:zoom.command(action)
        _,top=zoom.project(base,normal);self.assertEqual(top.point(top.x,top.y),(0,0))
        zoom.command(2)
        for action in [4,6]*15:zoom.command(action)
        _,end=zoom.project(base,normal);self.assertEqual(end.point(end.x+end.w-1,end.y+end.h-1),(10000,10000))
        zoom.command(0);self.assertEqual(zoom.project(base,normal)[1],normal)

    def test_zoom_receipt_follows_commit_and_keyboard_tracks_focus_during_refresh(self):
        frame,normal=fit_frame(Image.new("RGB",(960,592),"#5c5877"),native=True)
        trace=[];forward=[];packets=[]
        class Commands:
            def put_nowait(self,r):
                if isinstance(r,FocusRequest):
                    if r.command is None:r.result="a"*32
                    elif r.revision=="a"*32:forward.append(r.command);r.result=True
                    r.done.set()
                else:forward.append(r)
        class Worker:
            source=object();stop=threading.Event();commands=Commands()
            def snapshot(self):return 1,frame,normal
        class Done(Exception):pass
        class Fake:
            capabilities=31;active=False
            def __init__(self,serial,touch,health):self.touch=touch;self.health=health;self.phase=0
            def begin(self):self.active=True
            def end(self):self.active=False
            def send(self,payload,seconds=2):
                packets.append(payload[0])
                if self.phase==1 and payload[0]==10:
                    self.touch(1,0,0);self.touch(2,0,0)
                    self.assert_wait=self.control(0x27,5,1)
                    if self.assert_wait:raise AssertionError("Receipt before physical commit")
            def next_line(self,deadline):
                if self.phase==0 and trace:
                    self.phase=1
                    assert not self.control(0x27,5,1)
                elif self.phase==1 and len(trace)==2:
                    assert packets[-1]==11
                    assert self.control(0x27,5,1)
                    self.touch(1,0,0);self.touch(2,0,0)
                    assert self.control(0x28,6,None)
                    for i,command in enumerate([{"type":"text","text":"q"},{"type":"text","text":"w"},
                                               {"type":"key","key":"backspace"},{"type":"key","key":"enter"}]):
                        assert self.control(0x24,7+i,command)
                    raise Done()
        def notice(kind,value):
            if kind=="paint":trace.append(value)
        with self.assertRaises(Done):serve(None,Worker(),link_factory=Fake,notice=notice)
        self.assertEqual(len(forward),5)
        self.assertEqual((forward[0]["x"],forward[0]["y"]),(round(240e4/959),round(148e4/591)))
        self.assertEqual([list(c.values())[-1] for c in forward[1:]],["q","w","backspace","enter"])
