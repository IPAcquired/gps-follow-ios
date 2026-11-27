"""Exchange authenticated application data over the existing bounded USB/SPI transport."""
import re
import struct
import time
from collections import deque
from math import ceil

from pair_channel import PiChannel, READY
from display_model import CLEAR, LANDSCAPE, PORTRAIT
from wired_desktop import Link

BEACON = b"\x05XIAO235\x01"
REQUEST = b"\x50"
ACK, TOUCH, BACK = 0x21, 0x22, 0x23
KEY,CAPS,INVALIDATE,ZOOM,FOCUS=0x24,0x25,0x26,0x27,0x28
ALLOWED_KEYS={"enter","escape","tab","backspace","delete","up","down","left","right","ctrl+c","ctrl+v","ctrl+a"}

class LinkEnded(RuntimeError):
    pass

class LocalBack(LinkEnded):
    pass

class PairWire(Link):
    def __init__(self, device, service_health, report=lambda **values:None):
        super().__init__(device, lambda *_: None, service_health)
        self.on_record = lambda _: None
        self.report=report
        self.readback=False
        self.next_readback=0

    def begin(self):
        self.write("HELLO"); self.expect("DESKTOP XIAO 1")
        self.write("CAPS"); self.expect("CAPS PAIR 1")
        self.write("INFO")
        until=time.monotonic()+.3
        while time.monotonic()<until:
            line=self.next_line(until)
            if line=="INFO XIAO-PAIR-LIGHTS 1 PIO-DMA PWM":
                self.readback=True
                break
            if line and line.startswith("ERROR"):break
        self.write("BEGIN"); self.expect("READY")
        self.active=True;self.last_ping=time.monotonic()

    def next_line(self, deadline):
        while time.monotonic() < deadline:
            if self.readback and self.active and time.monotonic()>=self.next_readback:
                self.next_readback=time.monotonic()+3
                self.write("LED?")
                self.write("STATS")
            line = super().next_line(deadline)
            if line and self.readback and (line.startswith("LED ") or line.startswith("STATS ")):
                parts=line.split()
                expected=12 if parts[0]=="LED" else 7
                if len(parts)==expected+1 and all(re.fullmatch(r"[0-9]{1,10}",item) for item in parts[1:]):
                    name="xiao_led_readback" if parts[0]=="LED" else "xiao_spi_counters"
                    self.report(**{name:[int(item) for item in parts[1:]]})
                continue
            if line is None or not line.startswith("UP "):
                return line
            code = line[3:]
            if re.fullmatch(r"(?:[a-fA-F0-9]{2}){1,57}",code):
                self.on_record(bytes.fromhex(code))
                return None  # let a caller waiting for an application ACK recheck immediately
        return None

    def pump(self, predicate, seconds):
        until = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= until:
                raise LinkEnded("Peer confirmation timed out.")
            self.next_line(min(until, time.monotonic()+0.06))


def wait_for_screen(wire, generation):
    marker=struct.pack(">I",generation)
    requested=False
    def receive(value):
        nonlocal requested
        requested |= value == REQUEST+marker
    wire.on_record=receive
    while not requested:
        sent=time.monotonic()
        wire.send(BEACON+marker)
        while not requested and time.monotonic()-sent < .5:
            wire.next_line(min(sent+.5,time.monotonic()+.055))


def authenticate(wire, key):
    channel=PiChannel(key)
    reply=None
    def prove(record):
        nonlocal reply
        next_proof=channel.accept(record)
        if next_proof is not None:
            reply=next_proof
    wire.on_record=prove
    wire.send(channel.hello())
    wire.pump(lambda: reply is not None,2.5)
    wire.on_record=channel.unwrap
    wire.send(reply)
    wire.pump(lambda: channel.ready,2.5)
    session=SecureSession(wire,channel)
    promote=getattr(wire,"after_authentication",None)
    if promote:promote(session)
    return session


class SecureSession:
    def __init__(self,wire,channel):
        self.wire,self.channel=wire,channel
        self.ack=0
        self.closed=False
        self.last_event=None
        self.capabilities=0
        self.surface=LANDSCAPE
        self.pending_control=None
        self.handled_control=None
        self.touch=lambda *_: None
        self.wire.on_record=self.receive
        self.last_proof=time.monotonic()
        self.scene_timings=None
        self.burst_timings=None

    def start_scene_timing(self):
        self.scene_timings=deque(maxlen=512)
        self.burst_timings=deque(maxlen=512)

    def preferred_surface(self):
        # CLEAR advertises authenticated capabilities without making a desktop live.
        self.send(CLEAR)
        if self.capabilities&0x40:return PORTRAIT
        if self.surface!=LANDSCAPE:raise LinkEnded("Viewport changed during the session.")
        return LANDSCAPE

    def select_portrait(self):
        if not self.capabilities&0x40:raise LinkEnded("Portrait capability unavailable.")
        self.send(struct.pack(">BBHH",0x12,ord("V"),*PORTRAIT))
        self.surface=PORTRAIT

    def wait_for_source(self,ready,seconds):
        if getattr(self.wire,"burst_limit",1)==1:
            return ready.wait(seconds)
        deadline=time.monotonic()+seconds
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:return ready.is_set()
            if ready.wait(min(.4,remaining)):return True
            if time.monotonic()<deadline:
                # This encrypted probe leaves the display blank while desktop capture
                # establishes its own authorizations. It renews the USB rate/proof only.
                self.send(b"\x0fF2",.7)

    def finish_scene_timing(self):
        samples=self.scene_timings
        bursts=self.burst_timings
        self.scene_timings=None
        self.burst_timings=None
        if not samples and not bursts:return {}
        summary={"scene_records_timed":len(samples)+sum(n for n,_ in bursts)}
        if bursts:
            duration=sorted(seconds for _,seconds in bursts)
            summary["scene_burst_transfers"]=len(bursts)
            for p in (50,95):
                summary[f"scene_burst_p{p}_ms"]=round(duration[ceil(len(duration)*p/100)-1]*1000,2)
        if not samples:return summary
        for index,name in enumerate(("bridge_ack","screen_ack_extra","record_total")):
            values=sorted(sample[index] for sample in samples)
            for percentile in (50,95):
                summary[f"{name}_p{percentile}_ms"]=round(values[ceil(len(values)*percentile/100)-1]*1000,2)
        return summary

    def receive(self,packet):
        clear=self.channel.unwrap(packet)
        if clear is None:
            return
        kind=clear[0]
        if kind==BACK and len(clear)==5:
            self.closed=True
            raise LocalBack("Local Back.")
        ordinary=(kind==ACK and len(clear)==5) or (kind==TOUCH and len(clear)==12)
        control=((kind==KEY and 9<=len(clear)<=32) or (kind==INVALIDATE and len(clear)==7)
                 or (self.capabilities&16 and ((kind==ZOOM and len(clear)==8) or (kind==FOCUS and len(clear)==7))))
        advertised=kind==CAPS and len(clear)==7 and clear[1]==1
        if ordinary or control or advertised:
            seen=int.from_bytes(clear[3:7] if control else clear[-4:],"big")
            if seen > self.channel.tx_counter or seen < self.ack:
                raise LinkEnded("Invalid application acknowledgement.")
            self.ack=seen
            self.last_proof=time.monotonic()
            if advertised:self.capabilities=clear[2]
            if control:
                seq=int.from_bytes(clear[1:3],"big")
                if not seq:raise LinkEnded("Invalid control event.")
                instruction=None
                if kind==KEY:
                    try:value=clear[8:].decode("ascii")
                    except UnicodeError:raise LinkEnded("Invalid key.") from None
                    if clear[7]==1 and all(32<=ord(c)<=126 for c in value):
                        instruction={"type":"text","text":value}
                    elif clear[7]==2 and value in ALLOWED_KEYS:
                        instruction={"type":"key","key":value}
                    else:raise LinkEnded("Invalid key.")
                elif kind==ZOOM:
                    if clear[7]>6:raise LinkEnded("Invalid viewport operation.")
                    instruction=clear[7]
                self.pending_control=(kind,seq,instruction)
            if kind==TOUCH:
                _,seq,state,x,y,_=struct.unpack(">BHBHHI",clear)
                if not seq or state not in (1,2) or x>=self.surface[0] or y>=self.surface[1]:
                    raise LinkEnded("Invalid pointer.")
                if seq!=self.last_event:
                    self.last_event=seq
                    self.touch(state,x,y)
                if self.capabilities&8:
                    self.pending_control=(kind,seq,None)

    def send(self,data,seconds=2):
        if not self.channel.ready or self.closed or time.monotonic()-self.last_proof>2:
            raise LinkEnded("Paired display lease ended.")
        start=time.monotonic()
        record=self.channel.wrap(data)
        wanted=self.channel.tx_counter
        self.wire.send(record,seconds)
        accepted=time.monotonic()
        self.wire.pump(lambda:self.ack==wanted,min(1.4,seconds))
        if self.scene_timings is not None:
            confirmed=time.monotonic()
            self.scene_timings.append((accepted-start,confirmed-accepted,confirmed-start))

    def send_graphics(self,fragments,seconds=1):
        if not self.channel.ready or self.closed or time.monotonic()-self.last_proof>2:
            raise LinkEnded("Paired display lease ended.")
        if (not 1<=len(fragments)<=self.wire.burst_limit or
                any(not 4<=len(f)<=40 or f[0] not in (7,10) for f in fragments)):
            raise ValueError("Invalid staged graphics fragment.")
        started=time.monotonic()
        frames=[self.channel.wrap(fragment) for fragment in fragments]
        wanted=self.channel.tx_counter
        self.wire.send_burst(frames,seconds)
        # An unauthenticated outer USB receipt never commits desktop pixels.
        if self.ack!=wanted:
            self.wire.remember_slow_route()
            raise LinkEnded("Screen authentication failed for the graphics transfer.")
        if self.burst_timings is not None:
            self.burst_timings.append((len(frames),time.monotonic()-started))

    def blank(self,reason):
        if self.closed or not self.channel.ready:
            return
        if reason not in (1,2,3,4) or not self.capabilities&32:
            self.send(b"\x03",.45)
            if reason not in (1,2,3,4) or not self.capabilities&32:return
        self.send(bytes((0x0e,reason)),.45)

    def adapter(self,_serial,touch,health):
        session=self
        self.touch=touch
        class View:
            active=False
            owns_final_clear=True
            def __init__(self):
                self.health=health
                self.touch=touch
                self.control=lambda kind,seq,value:False
            @property
            def capabilities(self):return session.capabilities
            @property
            def graphics_burst(self):return getattr(session.wire,"burst_limit",1)
            def send_graphics(self,fragments):
                self.health()
                session.send_graphics(fragments)
                self.drain()
            def drain(self):
                pending=session.pending_control
                if pending:
                    kind,seq,instruction=pending
                    if session.handled_control and session.handled_control[:2]==(kind,seq):
                        receipt=session.handled_control[2]
                    else:
                        result=True if kind==TOUCH else self.control(kind,seq,instruction)
                        if not result:return
                        receipt=13 if result=="reject" and session.capabilities&16 else 8
                    if receipt:
                        session.handled_control=(kind,seq,receipt)
                        session.pending_control=None
                        session.send(struct.pack(">BH",receipt,seq),1.4)
                        if session.pending_control==pending:session.pending_control=None
            def begin(self):self.active=True
            def select_portrait(self):
                self.health()
                session.select_portrait()
                self.drain()
            def send(self,data,seconds=2):
                self.health()
                session.send(data,seconds)
                self.drain()
            def next_line(self,deadline):
                self.health()
                result=session.wire.next_line(deadline)
                self.drain()
                return result
            def end(self):
                self.active=False;session.touch=lambda *_: None
        return View()
