"""Direct E32R35T USB serial transport for the same paired desktop record protocol."""
import contextlib
import json
import re
import secrets
import time
from pathlib import Path

import serial
from serial.tools import list_ports

PAIRED_BUILD = "flight-team-display-1.3.34-wired-paired"
SUPPORTED_BUILDS = (PAIRED_BUILD, PAIRED_BUILD + "-r2", PAIRED_BUILD + "-r3",
                    PAIRED_BUILD + "-r3.1", PAIRED_BUILD + "-r3.2", PAIRED_BUILD + "-r3.3")
DIRECT_ROUTE = Path.home() / ".config/orange-pi-wired-desktop/direct-topology"

def find_direct(expected_mac):
    if not isinstance(expected_mac, bytes) or len(expected_mac) != 6:
        return None, None
    try:
        allowed = DIRECT_ROUTE.read_text().strip()
    except OSError:
        return None, None
    if not re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", allowed):
        return None, None
    for p in list_ports.comports():
        if (p.vid,p.pid) != (0x1a86,0x7523): continue
        name = Path(p.device).name
        if not re.fullmatch(r"ttyUSB[0-9]+",name): continue
        sysnode = (Path("/sys/class/tty") / name / "device").resolve()
        parent = next((d for d in (sysnode,*sysnode.parents) if (d/"idVendor").is_file()),None)
        if parent is None or parent.name != allowed: continue
        try:
            if (parent/"idVendor").read_text().strip()!="1a86" or (parent/"idProduct").read_text().strip()!="7523": continue
            cookie = "direct-" + allowed + "-" + (parent/"devnum").read_text().strip()
        except OSError: continue
        return p.device, cookie
    return None,None

class DirectWire:
    def __init__(self, port, expected_mac, health):
        self.serial, self.mac, self.health = port, expected_mac, health
        self.on_record = lambda value: None
        self.buffer = bytearray()
        self.seq = secrets.randbelow(65535)+1
        self.req = secrets.randbelow(1000000)+1
        self.next_poll = 0
        self.active = False

    def request(self, action, deadline, **arguments):
        self.req = (self.req % 0xfffffffe)+1
        packet = (json.dumps(dict(action=action,request_id=self.req,**arguments),separators=(",",":"))+"\n").encode()
        if self.serial.write(packet) != len(packet):
            raise OSError("Direct screen write was incomplete.")
        while time.monotonic()<deadline:
            self.health()
            self.buffer.extend(self.serial.read(min(4096,self.serial.in_waiting or 1)))
            while b"\n" in self.buffer:
                row,_,self.buffer=self.buffer.partition(b"\n")
                try: received=json.loads(row)
                except (UnicodeError,ValueError): continue
                if isinstance(received,dict) and received.get("request_id")==self.req:
                    return received
            if len(self.buffer)>16384: raise ValueError("Direct serial response too long.")
        raise RuntimeError("Direct screen did not answer in time.")

    def begin(self):
        result=self.request("wired_status",time.monotonic()+1.5)
        if (result.get("display")!="Hosyond-E32R35T" or result.get("firmware") not in SUPPORTED_BUILDS
                or result.get("screen_mac")!=self.mac.hex() or result.get("paired") is not True):
            raise PermissionError("Direct endpoint is not the enrolled display.")
        self.active=True

    def exchange(self, sequence, payload, deadline):
        result=self.request("wired_usb_exchange",deadline,seq=sequence,down_hex=payload.hex())
        if type(result.get("busy")) is not bool or type(result.get("ack")) is not int:
            raise ValueError("Unexpected direct transport response.")
        if result["busy"]: return None
        up=result.get("up_hex")
        if not isinstance(up,str) or not re.fullmatch(r"(?:[a-fA-F0-9]{2}){0,57}",up):
            raise ValueError("Unexpected direct uplink.")
        if up: self.on_record(bytes.fromhex(up))
        return result["ack"]

    def send(self,payload,seconds=3):
        if not self.active or not isinstance(payload,bytes) or not 1<=len(payload)<=62:
            raise ValueError("Invalid direct link state or packet.")
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if self.exchange(self.seq,payload,deadline)==self.seq:
                self.seq = self.seq % 65535 + 1
                return
            self.health()
            time.sleep(.015)
        raise RuntimeError("Direct screen did not accept the record.")

    def next_line(self,deadline):
        self.health()
        delay=min(deadline,self.next_poll)-time.monotonic()
        if delay>0: time.sleep(delay)
        if time.monotonic()>=deadline: return None
        self.exchange(0,b"",time.monotonic()+.45)
        self.next_poll=time.monotonic()+.015
        return None

    def pump(self,predicate,seconds):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>=deadline: raise RuntimeError("Direct peer confirmation timed out.")
            self.next_line(deadline)

    def end(self):
        self.active=False

@contextlib.contextmanager
def open_direct(node,expected_mac,health):
    # Suppress modem-line pulses when opening the CH340 programming bridge.
    device=serial.Serial(port=None,baudrate=115200,timeout=.008,write_timeout=.35,exclusive=True)
    device.dtr=False
    device.rts=False
    device.port=node
    try:
        device.open()
        device.reset_input_buffer()
        yield DirectWire(device,expected_mac,health)
    finally:
        device.close()
