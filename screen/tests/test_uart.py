"""Run the Pi transport against the firmware's JSON parser, paired viewer and real codecs."""
import ctypes
import json
import math
import random
import struct
import sys
import time
import unittest
import zlib
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"pi"))
from direct_usb import DirectWire, PAIRED_BUILD, _rate_cooldown
from paired_wire import BEACON, LinkEnded, LocalBack, authenticate, wait_for_screen
from pair_channel import screen_pair_key

lib=ctypes.CDLL(str(Path(sys.argv[1]).resolve()))
lib.uart_take.restype=ctypes.c_char_p
jpeg=Path(sys.argv[2]).read_bytes()
del sys.argv[1:]
mac=bytes((2,3,4,5,6,7))
inner=bytes(range(1,33))
key=screen_pair_key(inner,mac)
head=b"\x09"+struct.pack(">3HI",len(jpeg),480,296,zlib.crc32(jpeg))
parts=[b"\x0a"+struct.pack(">H",off)+jpeg[off:off+37] for off in range(0,len(jpeg),37)]

class Model:
    port="fixture"
    def __init__(self):
        self.baudrate=115200
        self.data=bytearray()
        self.trace=[]
        self.damage=None
        self.at_slice=None
        self.mangle_receipt=False
        self.limit=2000000
        self.legacy=False
        self.realtime=False
        self.real_origin=time.monotonic()
        self.real_elapsed=0

    @property
    def in_waiting(self):return len(self.data)

    def step(self,ms=2):
        if self.realtime:
            elapsed=round(1000*(time.monotonic()-self.real_origin))
            ms=max(ms,elapsed-self.real_elapsed)
            self.real_elapsed=elapsed
        lib.uart_step(ms)
        out=lib.uart_take()
        if out and self.mangle_receipt:
            doc=json.loads(out);doc["up_hex"]="";out=json.dumps(doc).encode()+b"\n"
            self.mangle_receipt=False
        self.data.extend(out)

    def write(self,packet):
        if self.realtime:self.step(1)
        doc=json.loads(packet)
        self.trace.append((doc["action"],self.baudrate))
        if doc["action"]=="wired_status":
            if self.baudrate!=lib.uart_baud():return len(packet)
            response=dict(request_id=doc["request_id"],firmware=PAIRED_BUILD+("-r3.3" if self.legacy else "-r3.4"),
                          screen_mac=mac.hex(),paired=True,display="Hosyond-E32R35T",direct_burst=1)
            self.data.extend(json.dumps(response).encode()+b"\n")
            return len(packet)
        encoded=packet
        if self.damage and doc["action"]=="wired_usb_burst1":
            self.damage(doc);self.damage=None
            encoded=json.dumps(doc,separators=(",",":")).encode()+b"\n"
        if self.baudrate<=self.limit:
            lib.uart_write(encoded,len(encoded),self.baudrate)
        self.step()
        count=0
        while lib.uart_pending():
            count+=1
            if self.at_slice:self.at_slice(count)
            self.step()
        return len(packet)

    def read(self,size):
        if not self.data:
            time.sleep(.001)
            if self.realtime:self.step(1)
        size=min(size,17)
        value=bytes(self.data[:size]);del self.data[:size]
        return value

def prepare(rate=2000000,legacy=False,limit=2000000):
    lib.clear_all();lib.uart_reset();assert lib.enroll(inner)
    model=Model();model.limit=limit;model.legacy=legacy
    wire=DirectWire(model,mac,lambda:None,max_baud=rate);wire.begin()
    wire.send(BEACON+struct.pack(">I",42));model.step(240)
    wire.send(BEACON+struct.pack(">I",42));model.step(240)
    lib.open_view();model.step(10)
    return model,wire

def session_at(rate=2000000,legacy=False):
    dev,wire=prepare(rate,legacy)
    session=authenticate(wire,key)
    session.send(b"\x04")
    dev.step(12)
    return dev,wire,session

class NativeTransport(unittest.TestCase):
    def setUp(self):_rate_cooldown.clear()

    def test_complete_scene_all_rates_and_r33(self):
        for rate,legacy in ((115200,True),(115200,False),(921600,False),(2000000,False)):
            dev,wire,session=session_at(rate,legacy)
            self.assertEqual(lib.uart_baud(),rate)
            self.assertEqual(wire.baud,rate)
            session.send(head)
            before=len(dev.trace)
            wire.seq=65533
            for offset in range(0,len(parts),wire.burst_limit):
                window=parts[offset:offset+wire.burst_limit]
                if len(window)>1: session.send_graphics(window)
                else:session.send(window[0])
            took=len(dev.trace)-before
            self.assertEqual(took,math.ceil(len(parts)/wire.burst_limit))
            self.assertEqual(lib.frames(),0)
            session.send(b"\x0b")
            self.assertEqual(lib.frames(),1)
            self.assertNotEqual(lib.at(415,75),lib.at(3,3))
            print(f"fixture jpeg={len(jpeg)} fragments={len(parts)} baud={rate} legacy={legacy} transfers={took}")

    def test_rejects_truncation_excess_and_bad_tag(self):
        cases=(lambda doc:doc.update(records=doc["records"][:-2]),
               lambda doc:doc.update(records=doc["records"]+"16"+"63"+"00"*21),
               lambda doc:doc.update(records=doc["records"][:-2]+("00" if doc["records"][-2:]!="00" else "01")))
        for damage in cases:
            dev,wire,session=session_at();session.send(head);dev.damage=damage
            with self.assertRaises(RuntimeError):session.send_graphics(parts[:8])
            self.assertEqual(lib.frames(),0)

    def test_outer_receipt_without_authenticated_ack(self):
        dev,wire,session=session_at();session.send(head);dev.mangle_receipt=True
        with self.assertRaises(LinkEnded):session.send_graphics(parts[:8])
        self.assertEqual(lib.frames(),0)

    def test_replay_and_disallowed_clear(self):
        dev,wire,session=session_at();session.send(head)
        def transmit(clear,seq):
            encrypted=session.channel.wrap(clear)
            args=dict(first=seq,records=(bytes([len(encrypted)])+encrypted).hex())
            reply=wire.request("wired_usb_burst1",time.monotonic()+.3,**args)
            return args,reply
        args,result=transmit(parts[0],99)
        self.assertEqual(result["accepted"],1)
        replay=wire.request("wired_usb_burst1",time.monotonic()+.3,**args)
        self.assertEqual(replay["accepted"],0)
        _,result=transmit(b"\x03",100)
        self.assertEqual(result["accepted"],0)
        self.assertTrue(lib.flags()&2)

    def test_guard_and_local_back_interrupt_a_window(self):
        for event in ("guard","back"):
            dev,wire,session=session_at();session.send(head)
            if event=="guard":
                dev.at_slice=lambda n:lib.uart_guard(True) if n==2 else None
            else:
                # Inject a real Back touch while fragments are staged.
                def back(n):
                    if n==1:lib.tap(True,30,311)
                    if n==3:lib.tap(False,30,311)
                dev.at_slice=back
            with self.assertRaises(RuntimeError) as error:session.send_graphics(parts[:8])
            if event=="back":self.assertIsInstance(error.exception,LocalBack)
            self.assertEqual(lib.frames(),0)

    def test_mid_burst_touch_and_authenticated_receipt(self):
        dev,wire,session=session_at();session.send(head)
        touches=[];session.touch=lambda *args:touches.append(args)
        def press(n):
            if n==1:lib.tap(True,35,44)
            if n==4:lib.tap(False,35,44)
        dev.at_slice=press
        view=session.adapter(dev,session.touch,lambda:None)
        view.send_graphics(parts[:8])
        view.next_line(time.monotonic()+.15)
        self.assertEqual(touches,[(1,35,44),(2,35,44)])

    def test_rate_switch_requires_auth_and_recovers_automatically(self):
        dev,wire=prepare()
        reply=wire.exchange(1455,b"\x0fF3",time.monotonic()+.2)
        self.assertNotEqual(reply,1455);self.assertEqual(lib.uart_baud(),115200)
        result=wire.request("wired_usb_burst1",time.monotonic()+.3,first=4,records="16"+"63"+"00"*21)
        self.assertEqual(result["error"],"rejected_burst")
        session=authenticate(wire,key)
        self.assertEqual(lib.uart_baud(),2000000)
        for _ in range(7):dev.step(200);wire.exchange(0,b"",time.monotonic()+.2)
        self.assertEqual(lib.uart_baud(),2000000)
        dev.step(201)
        self.assertEqual(lib.uart_baud(),115200)

    def test_high_rate_failure_steps_down(self):
        for expected in (2000000,921600):
            dev,wire=prepare(limit=115200)
            with self.assertRaises(RuntimeError):authenticate(wire,key)
            self.assertEqual(wire.baud,expected)
            dev.step(1610);self.assertEqual(lib.uart_baud(),115200)
        _,wire=prepare(limit=115200);session=authenticate(wire,key)
        self.assertEqual(wire.baud,115200)
        session.send(b"\x04");session.send(head);session.send_graphics(parts[:8])

    def test_short_rate_proof_passes_but_corrupt_bulk_steps_down(self):
        for rate in (2000000,921600):
            dev,wire,session=session_at()
            self.assertEqual(wire.baud,rate)
            session.send(head)
            def corrupt(doc):
                last=int(doc["records"][-2:],16)^1
                doc["records"]=doc["records"][:-2]+f"{last:02x}"
            dev.damage=corrupt
            with self.assertRaises(RuntimeError):session.send_graphics(parts[:8])
            self.assertEqual(lib.frames(),0)
        _,wire,session=session_at()
        self.assertEqual(wire.baud,115200)
        session.send(head);session.send_graphics(parts[:8])

    def test_slow_first_capture_keeps_proof_fresh_without_showing_desktop(self):
        dev,wire=prepare()
        session=authenticate(wire,key)
        class CaptureReady:
            waits=0
            def wait(self,seconds):
                self.waits+=1
                dev.step(round(1000*seconds))
                return self.waits==6
            def is_set(self):return self.waits>=6
        self.assertTrue(session.wait_for_source(CaptureReady(),3))
        self.assertEqual(lib.uart_baud(),2000000)
        self.assertFalse(lib.flags()&2)
        session.send(b"\x04");session.send(head);session.send_graphics(parts[:8])

    def test_first_connection_after_host_crash_without_resetting_screen(self):
        dev,old,session=session_at()
        session.send(head);session.send_graphics(parts[:8])
        self.assertEqual(lib.frames(),0)
        dev.realtime=True;dev.real_origin=time.monotonic()
        dev.baudrate=115200
        replacement=DirectWire(dev,mac,lambda:None)
        replacement.begin()
        self.assertEqual(lib.uart_baud(),115200)
        wait_for_screen(replacement,42)
        fresh=authenticate(replacement,key)
        fresh.send(b"\x04");fresh.send(head);fresh.send_graphics(parts[:8])
        self.assertEqual(lib.uart_baud(),2000000)

    def test_noise_yields_then_normal_input_resumes(self):
        dev,wire=prepare()
        noise=b"z"*6000+b"\n"
        lib.uart_write(noise,len(noise),115200);dev.step()
        self.assertEqual(lib.uart_unread(),len(noise)-1152)
        for _ in range(5):dev.step()
        self.assertEqual(lib.uart_unread(),0)
        session=authenticate(wire,key);session.send(b"\x04")

    def test_largest_legal_scene_and_envelope_then_reject_oversize(self):
        dev,wire,session=session_at()
        extra=16384-len(jpeg)
        full=jpeg[:2]+b"\xff\xfe"+struct.pack(">H",extra-2)+b"z"*(extra-4)+jpeg[2:]
        self.assertEqual(len(full),16384)
        session.send(b"\x09"+struct.pack(">3HI",len(full),480,296,zlib.crc32(full)))
        packets=[b"\x0a"+struct.pack(">H",off)+full[off:off+37] for off in range(0,len(full),37)]
        wire.req=0xfffffffd;wire.seq=65535
        for offset in range(0,len(packets),8):
            session.send_graphics(packets[offset:offset+8])
        session.send(b"\x0b")
        self.assertEqual(lib.frames(),1)
        body=session.channel.wrap(b"\x09"+struct.pack(">3HI",16385,480,296,0))
        wanted=wire.seq
        self.assertNotEqual(wire.exchange(wanted,body,time.monotonic()+.3),wanted)
        self.assertEqual(lib.frames(),1)

    def test_maximum_pixel_dirty_tile_and_preferred_helper_interruption(self):
        dev,wire,session=session_at()
        pixels=random.Random(123).randbytes(4096)
        packed=zlib.compress(pixels)
        self.assertGreater(len(packed),4096)
        session.send(b"\x06"+struct.pack(">5H",20,40,64,32,len(packed)))
        pieces=[b"\x07"+struct.pack(">H",i)+packed[i:i+37] for i in range(0,len(packed),37)]
        for offset in range(0,len(pieces),8):
            session.send_graphics(pieces[offset:offset+8])
        self.assertEqual(lib.tiles(),1)
        self.assertEqual(lib.at(20,40),int.from_bytes(pixels[:2],"big"))
        self.assertEqual(lib.at(83,71),int.from_bytes(pixels[-2:],"big"))
        session.send(head)
        beacon=BEACON+struct.pack(">I",867)
        def attach(n):
            if n<=2:
                lib.send_spi(n,beacon,len(beacon),True)
                dev.step(240)
        dev.at_slice=attach
        with self.assertRaises(RuntimeError):session.send_graphics(parts[:8])
        self.assertEqual(lib.frames(),0)

if __name__=="__main__":unittest.main(verbosity=2)
