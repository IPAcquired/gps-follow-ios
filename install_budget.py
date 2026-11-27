"""Add the review-only CPU budget to a verified v1.0.0 model-review installation."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import tempfile


BASE="7eacc8a551fedbaab9b638cff787f8cf77e297d3d6564dbf8dbcefebb57c08cb"
MODULE="orangepi_model_review.py"
HELPER="orangepi_review_budget.py"
ORIGINAL=b'    with team["acquire_orchestration_lock"]():\n'
BOUND=b'    from orangepi_review_budget import capped_services\n    with team["acquire_orchestration_lock"](), capped_services(team):\n'


def sha(data):return hashlib.sha256(data).hexdigest()


def trusted(p,directory=False):
    s=p.lstat()
    if p.resolve()!=p or not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode)) or s.st_uid!=os.getuid() or s.st_mode&0o022:
        raise RuntimeError("Unexpected local file ownership or permissions")


def read(p):
    try:trusted(p)
    except FileNotFoundError:return None
    return p.read_bytes()


def put(p,data):
    if data is None:p.unlink(missing_ok=True)
    else:
        mode=stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o600
        with tempfile.NamedTemporaryFile(dir=p.parent,delete=False) as f:
            tmp=Path(f.name);os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
        try:os.replace(tmp,p)
        finally:tmp.unlink(missing_ok=True)
    fd=os.open(p.parent,os.O_DIRECTORY|os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def install(home,forward,expected=BASE,write=put):
    folder=home/"bin";trusted(folder,True)
    src=folder/MODULE;helper=folder/HELPER
    state=home/".local/share/orangepi-review-budget-update"
    state.mkdir(mode=0o700,parents=True,exist_ok=True);trusted(state,True)
    if state.stat().st_mode&0o077:raise RuntimeError("Expected a private update directory")
    old=read(state/"original.py")
    cur=read(src);curhelper=read(helper)
    if old is None:
        if cur is None or sha(cur)!=expected or curhelper is not None:raise RuntimeError("Expected the verified v1.0.0 review module")
        old=cur
        if not forward:return
        put(state/"original.py",old)
    if sha(old)!=expected or old.count(ORIGINAL)!=1:raise RuntimeError("Unrecognized retained baseline")
    new=old.replace(ORIGINAL,BOUND)
    candidate=Path(__file__).resolve().with_name(HELPER).read_bytes()
    compile(new,MODULE,"exec");compile(candidate,HELPER,"exec")
    if cur not in (old,new) or curhelper not in (None,candidate):
        raise RuntimeError("Active files changed outside this update")
    # Both intermediate states are recoverable by rerunning this exact package.
    targets=[(helper,candidate),(src,new)] if forward else [(src,old),(helper,None)]
    try:
        for p,value in targets:
            if read(p)!=value:write(p,value)
        if any(read(p)!=v for p,v in targets):raise RuntimeError("Readback differs")
    except BaseException:
        put(src,cur);put(helper,curhelper)
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("install","rollback"));a=p.parse_args()
    if os.getuid()==0:raise SystemExit("Run as the existing desktop owner")
    home=Path.home();lock=home/".local/state/orangepi-model-orchestrator.lock"
    fd=os.open(lock,os.O_RDWR|os.O_NOFOLLOW)
    with os.fdopen(fd,"rb+") as f:
        trusted(lock)
        try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("A model is in use. Retry when the shared lock is free.")
        if (Path(os.environ["XDG_RUNTIME_DIR"])/"orangepi-review-budget/lease.json").exists():
            raise SystemExit("A model budget is still being restored. Retry after its recovery watcher completes.")
        install(home,a.action=="install")
    print("Review-only resource budget "+("installed" if a.action=="install" else "removed"))


if __name__=="__main__":main()
