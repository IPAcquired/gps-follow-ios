"""Exercise real production UI transport and AES/HMAC code through emulated LCD, USB and SPI."""
import ctypes as c
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/"pi"))
from pair_channel import PiChannel,screen_pair_key

lib=c.CDLL(str(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/"tests/auto-host-r3.so"))
inner=bytes(range(1,33))
key=screen_pair_key(inner,bytes([2,3,4,5,6,7]))
on=lambda flag:bool(lib.flags()&flag)
lib.drawn_status.restype=c.c_char_p
def step(ms=250,permit=True):lib.step(ms,permit)
def beacon(gen=42):return b"\x05XIAO235\x01"+struct.pack(">I",gen)
def usb(seq=0,body=b"",permit=True):
    out=c.create_string_buffer(57)
    packed=lib.direct(seq,body,len(body),permit,out)
    return bool(packed>>24), (packed>>8)&65535,out.raw[:packed&255]
def spi(seq,body,valid=True):
    lib.send_spi(seq,body,len(body),valid);step()
def spi_up():
    out=c.create_string_buffer(57)
    size=lib.spi_up(out);return out.raw[:size]
def handshake():
    pi=PiChannel(key);hello=pi.hello()
    _,ack,proof=usb(31,hello);assert ack==31
    proof2=pi.accept(proof);assert proof2
    _,ack,ready=usb(32,proof2);assert ack==32 and pi.unwrap(ready)==b"\x20"
    return pi
def setup():
    lib.clear_all();assert lib.enroll(inner)
    usb(1,beacon());step();usb(2,beacon());step()
    assert on(4) and on(8);lib.open_view();step()
    assert usb()[2]==b'\x50\x00\x00\x00\x2a'
import io,math,time,zlib
setup()
p=handshake();seq=40
def msg(b):
 global seq
 seq+=1
 _,ack,up=usb(seq,p.wrap(b))
 assert ack==seq, (seq,b[0])
 return p.unwrap(up)
def press(x,y):
 lib.tap(True,x,y);step(12);lib.tap(False,x,y);step(12)
def ackevent(u):
 return msg(b'\x08'+u[1:3])
def jbegin(buf):
 return b'\x09'+struct.pack(">3HI",len(buf),480,296,zlib.crc32(buf)&0xffffffff)
def pieces(buf,opcode):
 for off in range(0,len(buf),37):
  yield bytes((opcode,))+struct.pack(">H",off)+buf[off:off+37]
def revive():
 global p,seq
 setup();p=handshake();seq=40;assert msg(b'\x04')[:3]==b'\x25\x01\x3f';step(10)
assert msg(b'\x04')[:3]==b'\x25\x01\x3f'
rect=b'\x01'+struct.pack(">5H",10,20,18,22,0xf800)
assert msg(rect)[0]==0x21 and lib.at(10,20)==0xf800
step(10);press(12,24);got=p.unwrap(usb()[2]);assert got[0]==0x22 and got[3]==1
up=ackevent(got);assert up[0]==0x22 and up[3]==2
assert msg(b'\x08'+got[1:3])[1:3]==up[1:3];assert ackevent(up)[0]==0x21
def open_keys():
 press(444,306);request=p.unwrap(usb()[2]);assert request[0]==0x28 and not lib.keys_visible()
 ackevent(request);step(12);assert lib.keys_visible()
open_keys()
press(4,180);press(56,180);key1=p.unwrap(usb()[2]);assert key1[0]==0x24 and key1[7:]==b'\1q'
key2=ackevent(key1);assert key2[7:]==b'\1w';assert ackevent(key2)[0]==0x21
press(454,278);reset=p.unwrap(usb()[2]);assert not lib.keys_visible() and reset[0]==0x26;ackevent(reset)
press(360,306);press(202,236);zoom=p.unwrap(usb()[2]);assert zoom[0]==0x27 and zoom[7]==1 and lib.zoom_wait()
press(120,100);assert msg(b'\x04')[:3]==zoom[:3]
ackevent(zoom);assert lib.zoom_level()==2 and not lib.zoom_wait();step(10)
press(360,306);press(110,272);pan=p.unwrap(usb()[2]);assert pan[0]==0x27 and pan[7]==4;ackevent(pan);step(10)
press(360,306);press(20,236);zoom=p.unwrap(usb()[2]);assert zoom[7]==0;ackevent(zoom);assert lib.zoom_level()==1;step(10)
open_keys();press(4,180);press(56,180);key1=p.unwrap(usb()[2]);assert key1[0]==0x24
after=msg(b'\x0d'+key1[1:3]);assert not lib.keys_visible() and after[0]==0x26;ackevent(after);step(12)
press(444,306);focus=p.unwrap(usb()[2]);assert focus[0]==0x28
assert msg(b'\x0d'+focus[1:3])[0]==0x21 and not lib.keys_visible()
frame=(ROOT/'tests'/'fixture-desktop.jpg').read_bytes()
assert len(frame)<16384
old=lib.count_paints();msg(jbegin(frame))
for block in pieces(frame,10):msg(block)
assert lib.at(10,20)==0xf800 and lib.count_paints()==old
start=time.perf_counter();msg(b'\x0b');t=time.perf_counter()-start
assert lib.frames()==1 and lib.count_paints()==old+1 and lib.at(415,75)!=0 and lib.at(415,75)!=lib.at(3,3)
print("Staged synthetic editor JPEG:",len(frame),"bytes;",math.ceil(len(frame)/37)+2,"records; no updates visible before commit; host LCD/decoder fixture commit",round(t*1000,2),"ms (not ESP timing).")
raw=(b'\x07\xe0\x00\x1f')*(64*32//2);compressed=zlib.compress(raw);msg(b'\x06'+struct.pack('>5H',19,11,64,32,len(compressed)))
for block in pieces(compressed,7):msg(block)
assert lib.tiles()==1 and lib.at(19,11)==0x07e0 and lib.at(20,11)==0x001f and lib.at(82,42)==0x001f
assert usb(700,b'\x04')[1]!=700
def reject(clear):
 seq0=60000;_,a,_=usb(seq0,p.wrap(clear))
 assert a!=seq0 and not on(2)
revive();reject(b'\x06'+struct.pack('>5H',479,295,2,2,25))
revive();msg(jbegin(frame));reject(b'\x0b')
revive();msg(jbegin(frame));reject(b'\x0a\x00\x01x')
revive();bad=frame[:-4]+b'xxzz';msg(jbegin(bad))
for block in pieces(bad,10):msg(block)
reject(b'\x0b')
revive();msg(b'\x06'+struct.pack('>5H',0,0,1,1,len(compressed)))
for bl in list(pieces(compressed,7))[:-1]:msg(bl)
reject(list(pieces(compressed,7))[-1]);assert not lib.tiles()
revive();press(16,30);step(2850);assert not on(2) and not lib.keys_visible()
revive()
for i in range(7):press(12,20)
assert not on(2) and lib.overflows() and lib.drawn_status()==b'Desktop input interrupted'
hello=PiChannel(key).hello()
assert usb(244,hello)[1]==244 and lib.drawn_status()==b'Verifying paired Orange Pi'
revive();press(15,306);assert not on(1) and on(32) and p.unwrap(usb()[2])[0]==0x23
# Identical rapid edge sequence on physical SPI route, without a host poll between edges.
lib.clear_all();assert lib.enroll(inner)
spi(1,beacon(99));spi(2,beacon(99));step();assert on(4);lib.open_view();step(20)
def exchange(seq,body):spi(seq,body);step(20);return spi_up()
p=PiChannel(key);proof=p.accept(exchange(320,p.hello()));assert p.unwrap(exchange(321,proof))==b'\x20'
assert p.unwrap(exchange(322,p.wrap(b'\x04')))[:3]==b'\x25\x01\x3f'
press(30,40);press(30,40);got=p.unwrap(spi_up())
for seq,state in enumerate((1,2,1,2),324):
 assert got[0]==0x22 and got[3]==state
 got=p.unwrap(exchange(seq,p.wrap(b'\x08'+got[1:3])))
assert got[0]==0x21
assert lib.fast_fallbacks()==0
lib.light_reply();step(20);assert lib.fast_fallbacks()==0
spi(404,b'\x04',False);assert lib.fast_fallbacks()==0
spi(405,b'\x04',False);assert lib.fast_fallbacks()==1
for seq in range(440,458):
 u=p.unwrap(exchange(seq,p.wrap(b"\x04")));assert u is not None
assert lib.fast_promotions()==1
assert lib.probe_picture_store()==1
lib.connection_state.restype=c.c_char_p
def label():return lib.connection_state().decode()
press(15,306);assert not on(1) and on(32)
step(6100);spi(470,beacon(99));spi(471,beacon(99));step(12)
assert on(32) and not on(4) # restarting Pi / missing beacons alone cannot override Back
lib.confirm_harness_gap();assert not on(4) and label()=="Wired connection lost"
spi(472,beacon(99));assert not on(4)
spi(473,beacon(99));assert on(4) and not on(32)
lib.clear_all();assert lib.enroll(inner);lib.signal_helper(True,False);step(1000);lib.signal_helper(True,False)
assert not lib.connection_issue()
step(1000);lib.signal_helper(True,False);assert lib.connection_issue() and label()=="XIAO detected; waiting for Pi"
lib.signal_helper(False,True);assert label()=="Wired connection lost"
for flag in (0,1,2,4,5,6):
 args=[True,False,False,2800,False,False,False];args[flag]=not args[flag];assert not lib.auto_entry(*args)
assert not lib.auto_entry(True,False,False,2499,False,False,False) and lib.auto_entry(True,False,False,2501,False,False,False)
setup();p=handshake();seq=100
assert msg(b'\x03')[:3]==b'\x25\x01\x3f' and not on(2)
for code,expected in enumerate(("Pi desktop unavailable or locked","Pi safety check pending","Pi desktop service unavailable","Owner paused desktop sharing"),1):
 before=lib.count_paints();assert msg(bytes((14,code)))[0]==0x21
 assert label()==expected and lib.drawn_status().decode()==expected and not on(2) and not lib.keys_visible() and lib.count_paints()==before
assert usb(800,b'\x0e\x01')[1]!=800 and label()=="Owner paused desktop sharing"
msg(b'\x04');assert label()=="Waiting for first desktop image"
msg(rect);assert label()=="Wired desktop connected" and not lib.connection_issue() and not lib.drawn_status()
step(2900);assert label()=="Wired desktop stopped responding"
step(6400);assert label()=="Wired connection lost" and not on(1)
print("PASS stable SPI reattach with the same USB generation, Back suppression, physical-only status, protected UI gates and authenticated error/recovery states.")
print("PASS direct and SPI rapid edges, duplicate receipts, queued keys, local Back/keyboard, authenticated staged JPEG, exact bounded zlib, malformed/truncated data, overflow and expiry.")
