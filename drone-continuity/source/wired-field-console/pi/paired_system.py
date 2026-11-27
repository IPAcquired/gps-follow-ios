"""Private run state, paired identity, and the installed desktop broker's guard."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import threading
import time
try:
    import dbus
except ImportError:
    dbus=None

from desktop_source import DesktopUnavailable, OwnerDesktop, Pattern
from bridge_usb import selection
from pair_channel import pi_inner_key, screen_pair_key


def private_file(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>limit:
            raise PermissionError("Invalid owner-private file.")
        return f.read(limit+1)


def private_dir(path):
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    s=path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077:
        raise PermissionError("Invalid owner-private directory.")
    return path


def atomic_json(path,data):
    temporary=path.with_name("."+secrets.token_hex(12))
    fd=os.open(temporary,os.O_WRONLY|os.O_EXCL|os.O_CREAT,0o600)
    try:
        with os.fdopen(fd,"w") as file:
            json.dump(data,file)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime():
    return private_dir(Path("/run/user")/str(os.getuid())/"orange-pi-wired-desktop")


def enrollment():
    config=private_dir(Path.home()/".config/orange-pi-wired-desktop")
    seed=private_file(config/"pair.key",32)
    mac=private_file(config/"screen.mac",6)
    info=Path("/sys/class/sunxi_info/sys_info").read_text()[:16000]
    match=re.search(r"^\s*sunxi_serial\s*:\s*([a-fA-F0-9]{16,64})\s*$",info,re.M)
    if not match: raise PermissionError("Pi hardware binding unavailable.")
    return screen_pair_key(pi_inner_key(seed,match[1].lower()),mac)


def find_helper(topology):
    bridge,_=selection(topology)
    return (bridge.node,bridge.cookie) if bridge else (None,None)


def attach_generation(directory,cookie):
    route,_,instance=cookie.partition(":")
    filename=directory/("attachment-xiao.json" if route=="XIAO" else "attachment-direct.json")
    try: saved=json.loads(private_file(filename,512))
    except FileNotFoundError:
        try:saved=json.loads(private_file(directory/"attachment.json",512))
        except (FileNotFoundError,ValueError):saved={}
    except ValueError:saved={}
    generation=saved.get("generation",0)
    old_instance=saved.get("instance")
    same=old_instance==cookie or (route=="XIAO" and "/" in instance and old_instance=="XIAO:"+instance.split("/",1)[1])
    if not same or type(generation) is not int or not 0<generation<=0xffffffff:
        generation=secrets.randbelow(0xffffffff)+1
    if old_instance!=cookie or saved.get("generation")!=generation or not filename.exists():
        atomic_json(filename,{"instance":cookie,"generation":generation})
    return generation


_login_bus=threading.local()
def active_desktop():
    if dbus is not None:
        dest="org.freedesktop.login1"
        iface="org.freedesktop.DBus.Properties"
        try:
            if not getattr(_login_bus,"user",None):
                _login_bus.bus=dbus.SystemBus(private=True)
                _login_bus.user=_login_bus.bus.get_object(dest,"/org/freedesktop/login1/user/_"+str(os.getuid()),
                                                        introspect=False)
            # Re-read which session is primary and its current lock state on every call.
            session,path=_login_bus.user.Get(dest+".User","Display",dbus_interface=iface,timeout=.55)
            if not session or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}",str(session)):return False
            selected=_login_bus.bus.get_object(dest,path,introspect=False)
            fields=selected.GetAll(dest+".Session",dbus_interface=iface,timeout=.55)
            return (fields["User"][0]==os.getuid() and bool(fields["Active"]) and not bool(fields["LockedHint"])
                    and not bool(fields["Remote"]) and fields["Type"] in ("x11","wayland"))
        except (dbus.DBusException,KeyError,IndexError,TypeError):
            _login_bus.user=None
            if getattr(_login_bus,"bus",None):
                _login_bus.bus.close();_login_bus.bus=None
    return active_desktop_cli()

def active_desktop_cli():
    def query(args):
        p=subprocess.run(["/usr/bin/loginctl",*args],capture_output=True,text=True,timeout=1)
        if p.returncode: raise PermissionError("Login session unavailable.")
        return p.stdout.strip()
    uid=str(os.getuid())
    session=query(["show-user",uid,"-p","Display","--value"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}",session): return False
    names=("User","Active","LockedHint","Type","Remote")
    opts=[part for key in names for part in ("-p",key)]
    fields=dict(line.split("=",1) for line in query(["show-session",session,*opts]).splitlines() if "=" in line)
    return (fields.get("User")==uid and fields.get("Active")=="yes" and fields.get("LockedHint")=="no"
            and fields.get("Remote")=="no" and fields.get("Type") in ("x11","wayland"))


class Status:
    def __init__(self,directory):
        self.path=directory/"status.json";self.lock=threading.RLock()
        self.data={"state":"starting","authenticated":False,"pattern_verified":False,
                   "desktop_full_paints":0,"os_inputs":0,"updated_frame_after_input":0,
                   "updated_lcd_after_input":0}
        self.set()
    def set(self,**values):
        with self.lock:
            if values and all(self.data.get(k)==v for k,v in values.items()) and time.monotonic()-self.last_write<10:
                return
            self.data.update(values)
            self.last_write=time.monotonic()
            atomic_json(self.path,dict(self.data,updated_unix=int(time.time())))


class GuardedDesktop(OwnerDesktop):
    """A PSK proof may authorize only this finite nonce for the real broker."""
    def __init__(self,channel,status):
        super().__init__()
        self.channel,self.status=channel,status
        self.deadline=time.monotonic()+288
        self.frame_num=0
        self.after_frame=0
        self.changed_input=0
        self.captured_input=self.applied_inputs=0
        self.capture_times={}
        self.capture_lock=threading.Lock()
    def validate(self):
        if not self.channel.ready or time.monotonic()>=self.deadline:
            raise PermissionError("Paired or graphical session unavailable.")
        if not active_desktop():
            raise DesktopUnavailable(1)
    def open(self):
        self.validate();super().open()
    def frame(self):
        self.validate()
        began=time.monotonic()
        result=super().frame()
        if result:
            self.frame_num+=1
            with self.capture_lock:
                self.capture_times[self.frame_num]=began
                if len(self.capture_times)>800:
                    self.capture_times.pop(next(iter(self.capture_times)))
            if self.applied_inputs>self.captured_input:
                self.after_frame=self.frame_num
                self.changed_input=self.applied_inputs
                self.captured_input=self.applied_inputs
                self.status.set(updated_frame_after_input=self.applied_inputs)
        return result
    def focus(self):
        self.validate();return super().focus()
    def input(self,command,focus=None):
        self.validate();accepted=super().input(command,focus)
        if accepted:
            self.applied_inputs+=1
            self.status.set(os_inputs=self.applied_inputs)
        return accepted
    def paint(self,frame):
        values={"desktop_full_paints":self.status.data["desktop_full_paints"]+1}
        now=time.monotonic()
        with self.capture_lock:
            captured=self.capture_times.get(frame)
        if captured is not None:
            values.update(last_source_capture_monotonic=round(captured,4),
                          last_lcd_ack_monotonic=round(now,4),
                          capture_to_lcd_seconds=round(now-captured,3))
        if self.after_frame and frame>=self.after_frame and self.changed_input:
            values["updated_lcd_after_input"]=self.changed_input
        self.status.set(**values)


class GuardedPattern(Pattern):
    def __init__(self,channel,status):
        super().__init__();self.guard=GuardedDesktop(channel,status);self.checked=0
    def open(self):
        self.guard.open();self.checked=time.monotonic()
    def frame(self):
        # The broker implements guard checks inside unlock. Use a bounded test-only
        # nonce for these checks without capturing a desktop frame.
        if time.monotonic()-self.checked>.65:
            self.guard.validate();self.guard.open();self.checked=time.monotonic()
        return super().frame()
    def input(self,command):
        self.guard.validate()
        super().input(command)
    def close(self):self.guard.close()
