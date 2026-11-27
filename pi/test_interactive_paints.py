import io
import struct
import threading
import time
import unittest
import zlib
from dataclasses import replace
from PIL import Image, ImageChops, ImageDraw

from display_model import HEIGHT, WIDTH, Zoom, fit_frame, rgb565
from scene_codec import exchanges, interactive_plan, jpeg_scene, select_plan
from wired_desktop import serve


def white_box(frame):
    high,low=frame.split()
    table=[0]*255+[255]
    return ImageChops.darker(high.point(table),low.point(table)).getbbox()


class Worker:
    source=object()
    def __init__(self):
        self.stop=threading.Event()
        self.ident=0
        self.positions=[(7000,11000),(35000,31000),(56000,47000),(35000,31000)]
        self.frames=[]
        for n in range(4):
            image=Image.new("RGB",(WIDTH,HEIGHT),"#304559")
            draw=ImageDraw.Draw(image)
            for row in range(11):
                y=12+row*25
                draw.rectangle((49,y,206,y+8),fill=("#42586d" if n%2 else "#536879"))
                draw.text((65+n*13,y),"Display preferences     Apply",fill="#9aaebe")
            self.frames.append(fit_frame(image,native=True))
    def snapshot(self):
        frame,view=self.frames[self.ident%4]
        return self.ident,frame,replace(view,pointer=self.positions[self.ident%4])


class Receiver:
    capabilities=5
    owns_final_clear=True
    graphics_burst=8
    active=True
    def __init__(self,owner,worker,policy):
        self.owner,self.worker,self.policy=owner,worker,policy
        self.canvas=Image.new("LA",(WIDTH,HEIGHT))
        self.visible=[]
        self.objects=0
        self.jpeg_count=0
        self.tiles=0
    def start(self,*_):return self
    def begin(self):pass
    def end(self):pass
    def next_line(self,deadline):
        self.policy(self,"idle")
        time.sleep(.001)
    def send_graphics(self,packets):
        for packet in packets:self.send(packet)
    def send(self,p):
        op=p[0]
        if op in (6,9):
            self.kind=op
            self.buf=bytearray()
            if op==6:self.x,self.y,self.w,self.h,self.size=struct.unpack(">5H",p[1:])
            else:self.policy(self,"jpeg-start")
            return
        if op in (7,10):
            self.owner.assertEqual(int.from_bytes(p[1:3],"big"),len(self.buf))
            self.buf.extend(p[3:])
            if op==10:
                self.policy(self,"jpeg-receiving")
                return
            if len(self.buf)<self.size:return
            tile=Image.frombytes("LA",(self.w,self.h),zlib.decompress(self.buf))
            self.canvas.paste(tile,(self.x,self.y))
            self.tiles+=1
        elif op==11:
            jpeg=Image.open(io.BytesIO(self.buf)).convert("RGB")
            self.canvas=rgb565(jpeg)
            self.jpeg_count+=1
            self.owner.assertIsNone(white_box(self.canvas))
            self.visible.append(None)
            self.policy(self,"jpeg-complete")
            return
        elif op==1:
            x,y,w,h=struct.unpack(">4H",p[1:9])
            self.canvas.paste(tuple(p[9:]),(x,y,x+w,y+h))
        elif op==2:
            x,y,w=struct.unpack(">HHB",p[1:6])
            self.canvas.paste(Image.frombytes("LA",(w,1),p[6:]),(x,y))
        else:return
        self.objects+=1
        mark=white_box(self.canvas)
        if mark:
            self.owner.assertLessEqual(mark[2]-mark[0],13,"two cursor images")
            self.owner.assertLessEqual(mark[3]-mark[1],16,"two cursor images")
        self.visible.append(mark)
        self.policy(self,"drawn")


class InteractionTests(unittest.TestCase):
    def test_actionable_preview_and_unchanged_final_image(self):
        before=rgb565(Image.new("RGB",(WIDTH,HEIGHT),"#233747"))
        menu=Image.new("RGB",(WIDTH,HEIGHT),"#233747")
        draw=ImageDraw.Draw(menu)
        draw.rectangle((0,16,203,224),fill="#eeeef2",outline="#657789")
        for index in range(7):
            draw.text((18,34+index*24),"Open application",fill="#213445")
        target=rgb565(menu)
        jpeg=jpeg_scene(target)
        plan=interactive_plan(before,target,[(0,jpeg)],(20,6),8)
        self.assertIs(plan[-1][1],jpeg)
        self.assertLess(exchanges(plan[:-1],8),exchanges([plan[-1]],8))
        preview=before.copy()
        for _,patch in plan[:-1]:patch.apply(preview)
        self.assertEqual(preview.crop((20,34,29,43)).tobytes(),target.crop((20,34,29,43)).tobytes())
        rc2=select_plan(before,target,0,False,31,direct_usb=True)
        exact=interactive_plan(before,target,rc2,None,8)
        self.assertLessEqual(exchanges(exact,8),exchanges(rc2,8))
        final=before.copy()
        for _,patch in exact:patch.apply(final)
        self.assertEqual(final.tobytes(),target.tobytes())

    def test_hover_changes_preemption_rapid_reversals(self):
        worker=Worker()
        live=[False]
        motion=[0]
        def policy(peer,event):
            if live[0] and event=="drawn" and motion[0]<30:
                worker.ident+=1
                motion[0]+=1
        peer=Receiver(self,worker,policy)
        completed=[]
        def notice(kind,value):
            if kind=="paint":
                completed.append(value)
                if not live[0]:
                    live[0]=True
                    worker.ident+=1
        serve(None,worker,2.,link_factory=peer.start,notice=notice,direct_usb=True)
        self.assertGreaterEqual(motion[0],10)
        self.assertEqual(peer.jpeg_count,1)
        self.assertGreater(peer.tiles,10)
        self.assertLess(len(set(completed)),motion[0])
        self.assertGreaterEqual(len({box for box in peer.visible if box}),3)
        old=None
        for box in peer.visible:
            if old and box:
                self.assertEqual(old,box,"The previous position must be erased first")
            old=box

    def test_fresh_pointer_after_long_jpeg_zoom_and_new_session(self):
        worker=Worker()
        zoom=Zoom()
        for session in range(2):
            worker.stop=threading.Event()
            zoom=Zoom()
            pending=[None]
            zoomed=[False]
            zoom_request=[False]
            start_id=[0]
            def policy(peer,event):
                if event=="jpeg-start":
                    start_id[0]=worker.ident
                elif event=="jpeg-receiving":
                    worker.ident=start_id[0]+1
                elif event=="jpeg-complete":
                    _,frame,view=worker.snapshot()
                    pending[0]=white_box(zoom.project(frame,view)[0])
                elif event=="drawn" and pending[0] is not None:
                    self.assertEqual(white_box(peer.canvas),pending[0])
                    pending[0]=None
                elif event=="idle" and zoom_request[0]:
                    if not zoomed[0]:
                        zoom.command(1)
                        zoomed[0]=True
                    if peer.control(0x27,17,1):zoom_request[0]=False
            peer=Receiver(self,worker,policy)
            def notice(kind,value):
                if kind=="paint" and not zoomed[0]:zoom_request[0]=True
            serve(None,worker,1.8,link_factory=peer.start,notice=notice,direct_usb=True)
            self.assertTrue(zoomed[0])
            self.assertGreaterEqual(peer.jpeg_count,2)
            self.assertIsNone(pending[0])
            worker.ident+=1
