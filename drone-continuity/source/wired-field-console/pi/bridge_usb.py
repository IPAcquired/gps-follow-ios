"""Identify an individual USB bridge without opening any serial ports."""
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import NamedTuple


class Bridge(NamedTuple):
    node: str
    topology: str
    cookie: str
    digest: str


def serial_digest(serial):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{8,80}", serial) or len(set(serial)) < 3:
        raise ValueError("Bridge has no usable hardware serial.")
    return hashlib.sha256(b"xiao-rp2350-usb-v1\0" + serial.encode("ascii")).hexdigest()


def enumerate_bridges(dev=Path("/dev"), ttys=Path("/sys/class/tty")):
    result = []
    for node in dev.glob("ttyACM*"):
        if not re.fullmatch(r"ttyACM[0-9]+", node.name):
            continue
        try:
            interface = (ttys/node.name/"device").resolve(strict=True)
            parent = next(p for p in (interface,*interface.parents) if (p/"idVendor").exists())
            def prop(name):
                return (parent/name).read_text("ascii").strip()
            if not re.fullmatch(r"[0-9]+-[0-9]+(?:\.[0-9]+)*", parent.name):
                continue
            if (prop("idVendor"),prop("idProduct"),prop("product"),prop("authorized")) != (
                    "2886","0058","XIAO RP2350","1"):
                continue
            digest = serial_digest(prop("serial"))
            bus, device = prop("busnum"), prop("devnum")
            if not bus.isdecimal() or not device.isdecimal():
                continue
            result.append(Bridge(str(node),parent.name,f"{parent.name}/{bus}:{device}",digest))
        except (OSError,ValueError,StopIteration):
            continue
    return result


def read_pin(path):
    try:
        fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    with os.fdopen(fd,"rb") as stream:
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or
                s.st_mode & 0o077 or s.st_size > 68):
            raise PermissionError("Bridge identity file is not private.")
        value = stream.read().strip()
    if not re.fullmatch(b"[0-9a-f]{64}",value):
        raise ValueError("Bridge identity file is invalid.")
    return value.decode("ascii")


def pin_once(path, digest):
    """Install without replacing a previously enrolled hardware identity."""
    import tempfile
    if not re.fullmatch(r"[0-9a-f]{64}",digest):
        raise ValueError("Invalid bridge identity.")
    existing=read_pin(path)
    if existing is not None:
        if existing!=digest:raise PermissionError("A different bridge is already enrolled.")
        return
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="ascii") as f:
            f.write(digest+"\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(name,path)
        except FileExistsError:
            if read_pin(path) != digest:
                raise PermissionError("A different bridge is already enrolled.") from None
    finally:
        os.unlink(name)


def choose_bridge(bridges,topology,pin,candidate):
    if pin:
        matches = [b for b in bridges if b.digest==pin]
    elif candidate:
        # A single explicit migration candidate may receive discovery. The actual
        # serial pin is established only after a fresh proof from the paired ESP.
        matches = [b for b in bridges if b.digest==candidate] if len(bridges)==1 else []
    else:
        matches = [b for b in bridges if b.topology==topology]
    if len(matches)==1:
        return matches[0],"bridge selected"
    if not bridges:
        return None,"connect the USB data cable to the XIAO"
    if len(matches)>1 or (candidate and not pin and len(bridges)>1):
        return None,"multiple matching bridges; connect only the enrolled XIAO"
    return None,"check the enrolled XIAO or commission its USB identity"


def profile():
    return Path.home()/".config/orange-pi-wired-desktop"


def selection(topology):
    root = profile()
    return choose_bridge(enumerate_bridges(),topology,read_pin(root/"xiao-serial.sha256"),
                         read_pin(root/"xiao-migration.sha256"))


def confirm_bridge(topology,node,cookie,verified_session):
    if not verified_session.ready:
        raise PermissionError("A current paired screen proof is required.")
    selected,_ = selection(topology)
    if selected is None or (selected.node,selected.cookie)!=(node,cookie):
        raise PermissionError("Bridge changed during authentication.")
    root = profile()
    pin_once(root/"xiao-serial.sha256",selected.digest)
    (root/"xiao-migration.sha256").unlink(missing_ok=True)
