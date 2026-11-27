"""Stage, activate, or roll back the grounded proposal reviewer as the existing desktop owner."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from stage_changes import HASHES, stage

NAMES=("orangepi_model_review.py","orangepi-ai-team","orangepi-ai-improvement")


def sha(b):return hashlib.sha256(b).hexdigest()


def sync_dir(folder):
    fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def put(p,b,mode):
    if b is None:
        p.unlink(missing_ok=True);sync_dir(p.parent);return
    with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
        tmp=Path(f.name);f.write(b);f.flush();os.fchmod(f.fileno(),mode);os.fsync(f.fileno())
    try:os.replace(tmp,p);sync_dir(p.parent)
    finally:tmp.unlink(missing_ok=True)


def owned(path,directory=False):
    s=path.lstat()
    return s.st_uid==os.getuid() and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) and not s.st_mode&0o022


def read(p):
    try:
        if not owned(p):raise RuntimeError("Unexpected ownership, type or permissions for "+p.name)
        return p.read_bytes()
    except FileNotFoundError:return None


def paths(home):
    folder=home/".local/share/orangepi-model-review-update"
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not owned(folder,True) or folder.resolve()!=folder or folder.stat().st_mode&0o077:
        raise RuntimeError("Expected a private local update directory")
    return home/"bin",folder


def record(stage_dir):
    m=json.loads(read(stage_dir/"manifest.json"))
    old={};new={}
    for n in NAMES:
        old[n]=read(stage_dir/"prior"/n);new[n]=read(stage_dir/"new"/n)
        if ((sha(old[n]) if old[n] is not None else None)!=m["prior"][n] or new[n] is None or sha(new[n])!=m["new"][n]):
            raise RuntimeError("Retained update content differs")
    return old,new,m


def prepare(home=Path.home()):
    target,state=paths(home)
    if not owned(target,True):raise RuntimeError("Expected the desktop owner's bin directory")
    if (state/"manifest.json").exists():
        _,_,m=record(state)
        if m["kit"]!=kit_hash():raise RuntimeError("A different staged update already exists")
        return state
    old={n:read(target/n) for n in NAMES}
    if old[NAMES[0]] is not None or any(old[n] is None or sha(old[n])!=h for n,h in HASHES.items()):
        raise RuntimeError("Installed baseline differs from the verified release")
    prior=state/"prior";new=state/"new"
    prior.mkdir(mode=0o700,exist_ok=True);new.mkdir(mode=0o700,exist_ok=True)
    if not owned(prior,True) or not owned(new,True):raise RuntimeError("Unexpected stage directory")
    modes={}
    for n,b in old.items():
        modes[n]=stat.S_IMODE((target/n).stat().st_mode) if b is not None else 0o644
        if b is not None:put(prior/n,b,modes[n])
    stage(prior,new)
    manifest={"prior":{n:(sha(b) if b is not None else None) for n,b in old.items()},
              "new":{n:sha(read(new/n)) for n in NAMES},"modes":modes,"kit":kit_hash()}
    put(state/"manifest.json",json.dumps(manifest,sort_keys=True).encode(),0o600)
    record(state)
    return state


def kit_hash():
    src=Path(__file__).resolve().parent
    return sha(b"".join((src/n).read_bytes() for n in ("install_model_review.py","stage_changes.py","orangepi_model_review.py")))


def activate(home,forward,write=put):
    target,state=paths(home);old,new,m=record(state)
    if kit_hash()!=m["kit"]:raise RuntimeError("Use the same verified package for activation or rollback.")
    previous,desired=(old,new) if forward else (new,old)
    current={n:read(target/n) for n in NAMES}
    pending=state/"transaction.json"
    if pending.exists():
        journal=json.loads(read(pending))
        if journal not in ({"forward":True},{"forward":False}):raise RuntimeError("Unknown pending transaction")
        for n in NAMES:
            if current[n] not in (old[n],new[n]):raise RuntimeError("An installed file changed outside the interrupted transaction")
        recover=old if journal["forward"] else new
        for n in NAMES[::-1] if journal["forward"] else NAMES:
            put(target/n,recover[n],m["modes"][n])
        put(pending,None,0)
        current=recover
    if current==desired:return
    if current!=previous:raise RuntimeError("Active files changed after staging")
    put(pending,json.dumps({"forward":forward}).encode(),0o600)
    try:
        for n in NAMES if forward else reversed(NAMES):
            write(target/n,desired[n],m["modes"][n])
        if {n:read(target/n) for n in NAMES}!=desired:raise RuntimeError("Readback differs")
        if forward:
            env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1")
            for n in NAMES[1:]:
                subprocess.run([sys.executable,"-B",str(target/n),"--help"],cwd=home,env=env,
                               timeout=12,stdout=subprocess.DEVNULL,check=True)
        put(pending,None,0)
    except BaseException:
        for n in reversed(NAMES) if forward else NAMES:put(target/n,previous[n],m["modes"][n])
        if {n:read(target/n) for n in NAMES}==previous:put(pending,None,0)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("stage","activate","rollback"));args=p.parse_args()
    if os.getuid()==0:raise SystemExit("Run from the existing desktop owner's account.")
    home=Path.home();os.umask(0o077)
    lock=home/".local/state/orangepi-model-orchestrator.lock"
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"r+b") as handle:
        if not owned(lock):raise RuntimeError("Unexpected orchestration lock")
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("Another model review owns the shared lock. Retry after completion.")
        if args.action=="stage":print(prepare(home))
        else:activate(home,args.action=="activate");print("Verified "+args.action)


if __name__=="__main__":main()
