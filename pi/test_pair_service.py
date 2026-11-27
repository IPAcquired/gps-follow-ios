"""Exercise both cryptographic endpoints and service selection without a device or desktop."""
import contextlib
import hmac
import os
from pathlib import Path
import secrets
import struct
import tempfile
import time
import threading
import unittest
from unittest.mock import Mock,patch
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import auto_service
from paired_system import GuardedDesktop, attach_generation
from paired_wire import BEACON, REQUEST, LinkEnded, authenticate, wait_for_screen
from pair_channel import CONTEXT
from display_model import desktop_updates,fit_frame,initial_background,pattern_patches,patches,synthetic_frame
from desktop_source import FrameWorker
from paired_system import active_desktop
from PIL import Image


class TestWire:
    def __init__(self,key,*,valid_ack=True):
        self.key=key;self.valid_ack=valid_ack
        self.blocks=[];self.up=0;self.had_confirm=False;self.on_record=lambda _:None
    def send_up(self,clear):
        self.up+=1;header=b"\x64"+self.up.to_bytes(4,"big")
        self.on_record(header+self.u.encrypt(self.keys[72:80]+header[1:],clear,header))
    def send(self,p,seconds=3):
        self.blocks.append(p)
        if p.startswith(BEACON): self.on_record(REQUEST+p[-4:]);return
        if p[0]==0x60:
            self.nonce=p[1:];self.screen=secrets.token_bytes(16)
            proof=hmac.digest(self.key,CONTEXT+b"S"+self.nonce+self.screen,"sha256")[:16]
            self.on_record(b"\x61"+self.screen+proof);return
        if p[0]==0x62:
            expected=hmac.digest(self.key,CONTEXT+b"P"+self.nonce+self.screen,"sha256")[:16]
            if not hmac.compare_digest(expected,p[1:]): return
            self.keys=HKDF(algorithm=SHA256(),length=80,salt=self.nonce+self.screen,info=CONTEXT).derive(self.key)
            self.d=AESGCM(self.keys[:32]);self.u=AESGCM(self.keys[32:64]);self.up=0
            self.send_up(b"\x20");return
        assert p[0]==0x63
        clear=self.d.decrypt(self.keys[64:72]+p[1:5],p[5:],p[:5])
        self.had_confirm=clear==b"\x04"
        if self.valid_ack:self.send_up(b"\x21"+p[1:5])
    def pump(self,condition,seconds):
        if not condition():raise LinkEnded("Unconfirmed peer.")
    def next_line(self,deadline):return None


class Status:
    def __init__(self):self.data={}
    def set(self,**values):self.data.update(values)


class PairedServiceTests(unittest.TestCase):
    def test_socket_reuse_always_rechecks_login_session_and_lock(self):
        uid=os.getuid()
        fake=Mock()
        bus=fake.SystemBus.return_value;owner=Mock();seat=Mock()
        bus.get_object.side_effect=lambda name,path,**kwargs:owner if "/user/" in path else seat
        owner.Get.return_value=("c1","/session/1")
        state={"User":(uid,"/user"),"Active":True,"LockedHint":False,"Remote":False,"Type":"x11"}
        seat.GetAll.side_effect=lambda *args,**kwargs:state
        with patch("paired_system.dbus",fake),patch("paired_system._login_bus",threading.local()):
            self.assertTrue(active_desktop())
            for field,bad in [("LockedHint",True),("Remote",True),("User",(uid+1,"")),("Active",False)]:
                original=state[field];state[field]=bad;self.assertFalse(active_desktop());state[field]=original
            self.assertEqual(owner.Get.call_count,5);self.assertEqual(seat.GetAll.call_count,5)
            self.assertEqual(fake.SystemBus.call_count,1)

    def test_queued_inputs_precede_extra_capture_but_capture_gets_turn(self):
        trace=[]
        accepted=[]
        class Source:
            input_interval=.041
            def open(self):pass
            def close(self):pass
            def input(self,value):trace.append(value);accepted.append(time.monotonic())
            def frame(self):trace.append("capture");worker.stop.set()
        worker=FrameWorker(Source())
        for name in ("a","b","c"):worker.commands.put_nowait(name)
        worker.run()
        self.assertFalse(worker.error)
        self.assertEqual(trace,["a","b","capture"])
        self.assertGreaterEqual(accepted[1]-accepted[0],.040)

    def test_uncommissioned_auto_opens_actual_desktop(self):
        class Session:channel=object()
        s=auto_service.Service.__new__(auto_service.Service);s.status=Status();s.mode="auto"
        visited=[]
        s.run_view=lambda session,source,event:visited.append(type(source))
        with tempfile.TemporaryDirectory() as d,patch("auto_service.private_dir",return_value=Path(d)):
            s.display(Session(),bytes(range(32)))
        self.assertEqual(visited,[GuardedDesktop])

    def test_merged_full_image_is_pixel_exact(self):
        canvas=Image.new("LA",(480,296))
        target=canvas.copy()
        target.paste((15,86),(12,7,210,138));target.paste((135,246),(304,144,430,275))
        for i in range(30):
            target.putpixel((3*i,40),(i,i+1))
        old=list(patches(canvas,target))
        better=desktop_updates(canvas,target)
        self.assertLess(len(better),len(old))
        for _,part in better:part.apply(canvas)
        self.assertEqual(canvas.tobytes(),target.tobytes())

    def test_pattern_requires_three_draws_initially_then_one_for_tap(self):
        target,_=fit_frame(synthetic_frame())
        current=Image.new("LA", target.size)
        initial_background(target).apply(current)
        items=list(pattern_patches(current,target))
        self.assertEqual(len(items),2)
        for _,p in items:p.apply(current)
        self.assertEqual(current.tobytes(),target.tobytes())
        green,_=fit_frame(synthetic_frame(True))
        changed=list(pattern_patches(current,green))
        self.assertEqual(len(changed),1)
        changed[0][1].apply(current)
        self.assertEqual(current.tobytes(),green.tobytes())
    def test_cookie_change_and_stable_return(self):
        with tempfile.TemporaryDirectory() as path:
            d=Path(path);one=attach_generation(d,"XIAO:A")
            self.assertEqual(one,attach_generation(d,"XIAO:A"))
            self.assertNotEqual(one,attach_generation(d,"direct USB:B"))

    def test_mutual_proof_and_real_screen_ack_required(self):
        key=secrets.token_bytes(32);w=TestWire(key)
        wait_for_screen(w,7);self.assertEqual(w.blocks[0],BEACON+struct.pack(">I",7))
        conn=authenticate(w,key)
        conn.start_scene_timing()
        conn.send(b"\x04");self.assertTrue(w.had_confirm)
        timing=conn.finish_scene_timing()
        self.assertEqual(timing["scene_records_timed"],1)
        self.assertGreaterEqual(timing["record_total_p95_ms"],timing["bridge_ack_p95_ms"])
        self.assertNotIn(b"\x04",w.blocks)
        w.valid_ack=False
        with self.assertRaises(LinkEnded):conn.send(b"\x03")

    def test_wrong_and_replaced_endpoint_get_no_desktop_data(self):
        expected=secrets.token_bytes(32)
        for different_key in (secrets.token_bytes(32),bytes(32)):
            wire=TestWire(different_key)
            with self.assertRaises(LinkEnded):authenticate(wire,expected)
            self.assertEqual([p[0] for p in wire.blocks],[0x60])
        first=TestWire(expected);a=authenticate(first,expected);a.send(b"\x04")
        second=TestWire(expected);b=authenticate(second,expected)
        self.assertNotEqual(first.blocks[0],second.blocks[0])
        self.assertEqual(b.ack,0)

    def test_valid_touch_only_and_back(self):
        key=secrets.token_bytes(32);w=TestWire(key);c=authenticate(w,key)
        events=[];c.touch=lambda *args:events.append(args);c.send(b"\x04")
        touch=struct.pack(">BHBHHI",0x22,4,2,40,60,1)
        c.receive(touch)
        self.assertEqual(events,[])
        w.send_up(touch);w.send_up(touch)
        self.assertEqual(events,[(2,40,60)])
        with self.assertRaises(LinkEnded):w.send_up(b"\x23"+struct.pack(">I",1))
        with self.assertRaises(LinkEnded):c.send(b"\x04")

    def test_block_locked_or_disconnected_desktop_before_input(self):
        class Channel:ready=True
        src=GuardedDesktop.__new__(GuardedDesktop);src.channel=Channel();src.deadline=time.monotonic()+10
        with patch("paired_system.active_desktop",return_value=False),self.assertRaises(PermissionError):
            src.input({"type":"tap","x":0,"y":0,"button":"left"})
        src.channel.ready=False
        with patch("paired_system.active_desktop",side_effect=AssertionError),self.assertRaises(PermissionError):
            src.frame()

    def test_returned_key_and_pointer_are_acknowledged_and_deduplicated(self):
        key=secrets.token_bytes(32);w=TestWire(key);s=authenticate(w,key)
        touches=[];keys=[]
        view=s.adapter(None,lambda *args:touches.append(args),lambda:None)
        view.control=lambda kind,seq,command:keys.append((kind,command)) or True
        w.send_up(b"\x25\x01\x0f"+struct.pack(">I",0))
        def emit(message):
            w.send_up(message)
            view.drain()
        for _ in range(2):
            emit(struct.pack(">BHBHHI",0x22,1,1,200,60,s.ack))
        emit(struct.pack(">BHBHHI",0x22,2,2,200,60,s.ack))
        for _ in range(2):
            emit(struct.pack(">BHIB",0x24,3,s.ack,2)+b"enter")
        emit(struct.pack(">BHI",0x26,4,s.ack))
        self.assertEqual(s.capabilities,15)
        self.assertEqual(touches,[(1,200,60),(2,200,60)])
        self.assertEqual(keys,[(0x24,{"type":"key","key":"enter"}),(0x26,None)])
        self.assertEqual(s.ack,6)
        with self.assertRaises(LinkEnded):
            emit(struct.pack(">BHIB",0x24,5,s.ack,2)+b"unsupported")

    def test_route_preference_and_bounded_fallback(self):
        svc=auto_service.Service.__new__(auto_service.Service)
        svc.direct_attachment=auto_service.DirectAttachment()
        auth=secrets.token_bytes(32);selected=[]
        class Missing:
            def __init__(self,name):self.name=name
            def __enter__(self):selected.append(self.name);raise LinkEnded()
            def __exit__(self,*_):pass
        svc.controls=lambda:None;svc.open_xiao=lambda _:Missing("XIAO")
        svc.mode="auto";svc.topology="fake";svc.status=Status();svc.bad_xiao=None;svc.bad_count=0
        with tempfile.TemporaryDirectory() as temp,patch("auto_service.enrollment",return_value=auth),\
                patch("auto_service.private_file",return_value=b"\0"*6),\
                patch("auto_service.find_helper",return_value=("node","a")),\
                patch("auto_service.find_direct",return_value=("other","b")),\
                patch.object(svc.direct_attachment,"open",return_value=Missing("screen")):
            svc.dir=Path(temp)
            for _ in range(3):
                with self.assertRaises(LinkEnded):svc.once()
            self.assertEqual(selected,["XIAO","XIAO","screen"])
            self.assertIsNone(svc.route)

if __name__=="__main__":unittest.main()
