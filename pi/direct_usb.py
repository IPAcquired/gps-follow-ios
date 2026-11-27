"""Direct E32R35T USB serial transport for the same paired desktop record protocol."""
import contextlib
import errno
import fcntl
import json
import re
import secrets
import struct
import termios
import time
from pathlib import Path

import serial
from serial.tools import list_ports
from screen_sockets import approved_sockets, port_location

PAIRED_BUILD = "flight-team-display-1.3.34-wired-paired"
SUPPORTED_BUILDS = (PAIRED_BUILD, PAIRED_BUILD + "-r2", PAIRED_BUILD + "-r3",
                    PAIRED_BUILD + "-r3.1", PAIRED_BUILD + "-r3.2", PAIRED_BUILD + "-r3.3",
                    PAIRED_BUILD + "-r3.4")
BASE_BAUD = 115200
FAST_RATES = ((2000000,b"\x0fF3"),(921600,b"\x0fF1"))
BURST_LIMIT = 8
_rate_cooldown = {}
DIRECT_ROUTE = Path.home() / ".config/orange-pi-wired-desktop/direct-topology"

class DirectTimeout(RuntimeError):
    pass

def preferred_baud(node):
    if not node:
        return 2000000
    try:
        _,socket,_=port_location(node)
    except (OSError,ValueError):
        return 2000000
    return 921600 if "." in socket else 2000000

def find_direct(expected_mac):
    if not isinstance(expected_mac, bytes) or len(expected_mac) != 6:
        return None, None
    allowed = approved_sockets(DIRECT_ROUTE)
    if not allowed:
        return None, None
    for p in list_ports.comports():
        if (p.vid,p.pid) != (0x1a86,0x7523): continue
        name = Path(p.device).name
        if not re.fullmatch(r"ttyUSB[0-9]+",name): continue
        sysnode = (Path("/sys/class/tty") / name / "device").resolve()
        parent = next((d for d in (sysnode,*sysnode.parents) if (d/"idVendor").is_file()),None)
        if parent is None or parent.name not in allowed: continue
        try:
            if (parent/"idVendor").read_text().strip()!="1a86" or (parent/"idProduct").read_text().strip()!="7523": continue
            cookie = "direct-" + parent.name + "-" + (parent/"devnum").read_text().strip()
        except OSError: continue
        return p.device, cookie
    return None,None

class DirectWire:
    def __init__(self, port, expected_mac, health, max_baud=None):
        self.serial, self.mac, self.health = port, expected_mac, health
        self.on_record = lambda value: None
        self.buffer = bytearray()
        self.seq = secrets.randbelow(65535)+1
        self.req = secrets.randbelow(1000000)+1
        self.next_poll = 0
        self.active = False
        self.burst_limit = 1
        self.max_baud = preferred_baud(getattr(port,"port",None)) if max_baud is None else max_baud
        self.baud = BASE_BAUD
        self.route = (getattr(port, "port", None), expected_mac)

    def request(self, action, deadline, **arguments):
        self.req = (self.req % 0xfffffffe)+1
        packet = (json.dumps(dict(action=action,request_id=self.req,**arguments),separators=(",",":"))+"\n").encode()
        if self.serial.write(packet) != len(packet):
            self.remember_slow_route()
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
        if action!="wired_usb_exchange" or arguments.get("seq")!=0 or arguments.get("down_hex")!="":
            self.remember_slow_route()
        raise DirectTimeout("Direct screen did not answer in time.")

    def begin(self):
        # A host can vanish while the screen is at the higher rate. The last
        # identity probe starts after the 1.6 s watchdog and one normal UI pass.
        for attempt,timeout in enumerate((1.5,.7,1.5)):
            try:
                result=self.request("wired_status",time.monotonic()+timeout)
                break
            except DirectTimeout:
                if attempt==2:raise
        if (result.get("display")!="Hosyond-E32R35T" or result.get("firmware") not in SUPPORTED_BUILDS
                or result.get("screen_mac")!=self.mac.hex() or result.get("paired") is not True):
            raise PermissionError("Direct endpoint is not the enrolled display.")
        self.active=True
        if (result.get("firmware")==PAIRED_BUILD+"-r3.4" and
                type(result.get("direct_burst")) is int and result["direct_burst"]==1):
            self.burst_limit=BURST_LIMIT

    def after_authentication(self, session):
        if self.burst_limit==1:
            return
        for baud,command in FAST_RATES:
            if baud>self.max_baud or time.monotonic()<_rate_cooldown.get((self.route,baud),0):
                continue
            self.baud=baud
            try:
                session.send(command,.7)
                self.serial.baudrate=baud
                session.send(b"\x0fF2",.7)
            except (OSError,ValueError,RuntimeError):
                self.remember_slow_route()
                raise
            return

    def remember_slow_route(self):
        if self.baud!=BASE_BAUD:
            _rate_cooldown[self.route,self.baud]=time.monotonic()+300

    def classify_burst_rejection(self):
        if self.baud==BASE_BAUD:
            return
        # The screen also denies graphics when its local safety guard or Back
        # takes over. This read-only diagnostic only affects a future baud choice.
        try:
            status=self.request("wired_status",time.monotonic()+.35)
            if (status.get("screen_mac")==self.mac.hex() and status.get("paired") is True
                    and (status.get("guard") is True or status.get("priority_alert") is True
                         or status.get("back") is True)):
                return
        except (DirectTimeout,OSError,ValueError):
            pass
        self.remember_slow_route()

    def send_burst(self, packets, seconds):
        if (not self.active or not 1<=len(packets)<=self.burst_limit or self.burst_limit==1
                or any(not isinstance(p,bytes) or not 22<=len(p)<=61 or p[0]!=0x63 for p in packets)):
            raise ValueError("Invalid direct graphics burst.")
        records=b"".join(bytes((len(packet),))+packet for packet in packets)
        expected=(self.seq+len(packets)-2)%65535+1
        try:
            result=self.request("wired_usb_burst1",time.monotonic()+seconds,first=self.seq,records=records.hex())
            if result.get("busy") is True:
                raise RuntimeError("Direct screen stopped the graphics transfer.")
            if result.get("busy") is not False:
                self.classify_burst_rejection()
                raise RuntimeError("Direct screen rejected the graphics envelope.")
            self.uplink(result)
            if (type(result.get("ack")) is not int or result["ack"]!=expected
                    or type(result.get("accepted")) is not int or result["accepted"]!=len(packets)):
                self.classify_burst_rejection()
                raise RuntimeError("Direct screen did not acknowledge the full graphics transfer.")
        except (OSError,ValueError):
            self.remember_slow_route()
            raise
        self.seq=expected%65535+1

    def exchange(self, sequence, payload, deadline):
        result=self.request("wired_usb_exchange",deadline,seq=sequence,down_hex=payload.hex())
        if type(result.get("busy")) is not bool or type(result.get("ack")) is not int:
            raise ValueError("Unexpected direct transport response.")
        if result["busy"]: return None
        self.uplink(result)
        return result["ack"]

    def uplink(self,result):
        up=result.get("up_hex")
        if not isinstance(up,str) or not re.fullmatch(r"(?:[a-fA-F0-9]{2}){0,57}",up):
            raise ValueError("Unexpected direct uplink.")
        if up: self.on_record(bytes.fromhex(up))

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
        self.remember_slow_route()
        raise RuntimeError("Direct screen did not accept the record.")

    def next_line(self,deadline):
        self.health()
        delay=min(deadline,self.next_poll)-time.monotonic()
        if delay>0: time.sleep(delay)
        if time.monotonic()>=deadline: return None
        began=time.monotonic()
        try:
            self.exchange(0,b"",began+.45)
        except DirectTimeout:
            # Polls contain no application record and cannot advance an authenticated
            # counter. Keep one total budget, including the first unanswered poll.
            self.health()
            end=began+.85
            if time.monotonic()>=end:
                self.remember_slow_route()
                raise
            try:
                self.exchange(0,b"",end)
            except DirectTimeout:
                self.remember_slow_route()
                raise
        self.next_poll=time.monotonic()+.015
        return None

    def pump(self,predicate,seconds):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>=deadline:
                self.remember_slow_route()
                raise RuntimeError("Direct peer confirmation timed out.")
            self.next_line(deadline)

    def end(self):
        self.active=False

class DisplaySerial(serial.Serial):
    """The ESP32 auto-reset circuit requires both modem outputs to change together."""
    def _release_modem_lines(self):
        mask = struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS)
        # pySerial has opened fd but does not set is_open until after these two calls.
        fcntl.ioctl(self.fd, termios.TIOCMBIC, mask)

    # The POSIX pySerial open path calls these separately. The first ioctl
    # releases BOTH lines so there is never a software-requested RTS-only state.
    _update_dtr_state = _release_modem_lines
    _update_rts_state = _release_modem_lines


class DirectAttachment:
    """Keep one fd for the lifetime of the approved CH340 attachment."""
    def __init__(self):
        self.device = None
        self.identity = None

    def close(self):
        device, self.device = self.device, None
        self.identity = None
        if device is not None:
            device.close()

    @contextlib.contextmanager
    def open(self, node, cookie, expected_mac, health):
        identity = (node, cookie, expected_mac)
        if self.identity != identity:
            self.close()
            device = DisplaySerial(port=None, baudrate=BASE_BAUD, timeout=.008,
                                   write_timeout=.35, exclusive=True)
            device.dtr = device.rts = False
            device.port = node
            try:
                device.open()
                attributes = termios.tcgetattr(device.fileno())
                if attributes[2] & termios.HUPCL:
                    attributes[2] &= ~termios.HUPCL
                    termios.tcsetattr(device.fileno(), termios.TCSANOW, attributes)
            except BaseException:
                device.close()
                raise
            self.device, self.identity = device, identity
        try:
            if self.device.baudrate != BASE_BAUD:
                self.device.baudrate = BASE_BAUD
            self.device.reset_input_buffer()
            # A fresh transport and cryptographic proof are required on every
            # session, even when the underlying file descriptor is still open.
            yield DirectWire(self.device, expected_mac, health)
        except OSError as error:
            if (isinstance(error, serial.SerialException) and not isinstance(error,serial.SerialTimeoutException)
                    or error.errno in (errno.ENODEV, errno.EIO, errno.EBADF)):
                self.close()
            raise


@contextlib.contextmanager
def open_direct(node,expected_mac,health):
    """Single-session caller, e.g. commissioning, releases its own port."""
    attachment=DirectAttachment()
    try:
        with attachment.open(node,None,expected_mac,health) as wire:
            yield wire
    finally:
        attachment.close()
