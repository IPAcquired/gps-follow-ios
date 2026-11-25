"""Private Pi enrollment transaction. Binary output is consumed only by the local provisioner."""
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

ROOT = Path.home()/".config/orange-pi-wired-desktop"
PENDING = ROOT/".pending-screen-pair"
NAMES = ("screen.mac","direct-topology","pair.key")

def private_read(path,length=None):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb") as f:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise ValueError("Private enrollment permissions required.")
        data=f.read(129)
    if (length is not None and len(data)!=length) or len(data)>128:
        raise ValueError("Invalid enrollment record.")
    return data

def checked_dir(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
        raise ValueError("Invalid private enrollment directory.")

def save_exclusive(path,data):
    with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600),"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())

def sync_dir(path):
    fd=os.open(path,os.O_DIRECTORY|os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def inner(seed):
    v=Path("/sys/class/sunxi_info/sys_info").read_text()
    m=re.search(r"(?im)^\s*sunxi_serial\s*:\s*([a-f0-9]{16,64})\s*$",v)
    if not m:raise ValueError("Board hardware binding unavailable.")
    return hmac.digest(seed,b"wired-pi-v1\0"+m[1].lower().encode("ascii"),hashlib.sha256)

def run(mode):
    # Receive screen identity and approved cable location privately on standard input.
    content=sys.stdin.buffer.read(150)
    if len(content)<8 or not re.fullmatch(rb"[0-9]+-[0-9]+(?:\.[0-9]+)*",content[6:]):
        raise ValueError("Enrollment target unavailable.")
    mac,route=content[:6],content[6:]
    if not any(mac) or mac[0]&1: raise ValueError("Invalid device binding.")
    os.umask(0o077)
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    checked_dir(ROOT)
    lock=os.open(ROOT/".pair-lock",os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
    with os.fdopen(lock,"rb") as locked:
        fcntl.flock(locked,fcntl.LOCK_EX)
        if (ROOT/"pair.key").exists(): source=ROOT
        elif PENDING.is_dir():source=PENDING
        elif mode=="prepare":
            # Publish a complete pending directory with a single rename.
            prep=Path(tempfile.mkdtemp(prefix=".new-pair-",dir=ROOT))
            save_exclusive(prep/"screen.mac",mac)
            save_exclusive(prep/"pair.key",secrets.token_bytes(32))
            save_exclusive(prep/"direct-topology",route+b"\n")
            sync_dir(prep);prep.rename(PENDING);sync_dir(ROOT)
            source=PENDING
        else:raise ValueError("No pending enrollment.")
        checked_dir(source)
        seed=private_read(source/"pair.key",32)
        if not hmac.compare_digest(private_read(source/"screen.mac",6),mac):
            raise ValueError("A different screen already owns this pairing.")
        if not hmac.compare_digest(private_read(source/"direct-topology").strip(),route):
            raise ValueError("Approved physical path differs from the enrollment record.")
        if mode=="prepare":
            sys.stdout.buffer.write(inner(seed))
            return
        if mode!="activate":raise ValueError("Unsupported enrollment operation.")
        if source==PENDING:
            for name in NAMES:
                dest=ROOT/name
                if dest.exists():
                    if not hmac.compare_digest(private_read(dest),private_read(source/name)):
                        raise ValueError("Existing owner enrollment differs.")
                else:os.link(source/name,dest)
                sync_dir(ROOT)
        if PENDING.is_dir():
            checked_dir(PENDING)
            if all(hmac.compare_digest(private_read(ROOT/n),private_read(PENDING/n)) for n in NAMES):
                for n in NAMES:(PENDING/n).unlink()
                PENDING.rmdir();sync_dir(ROOT)
        print("ACTIVE")

if __name__=="__main__":
    try:run(sys.argv[1])
    except Exception:
        sys.stderr.write("Private enrollment could not be completed.")
        sys.exit(1)
