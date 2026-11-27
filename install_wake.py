"""Install or remove the passive proposal watcher for the existing field review kit."""
import argparse
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile

UNIT="orangepi-controller-review.path"
V1="7eacc8a551fedbaab9b638cff787f8cf77e297d3d6564dbf8dbcefebb57c08cb"
SOURCE=Path(__file__).resolve().with_name(UNIT)


def systemctl(*args,check=True):
    return subprocess.run(["systemctl","--user",*args],check=check,capture_output=True,text=True,timeout=30)


def managed_file(p,contents):
    try:s=p.lstat()
    except FileNotFoundError:return False
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o022 or p.read_bytes()!=contents:
        raise RuntimeError("Existing path unit differs from this release")
    return True


def deploy(home,action,ctl=systemctl,expected=V1):
    content=SOURCE.read_bytes()
    units=home/".config/systemd/user";target=units/UNIT
    units.mkdir(mode=0o700,parents=True,exist_ok=True)
    owned_tree=all(p.stat().st_uid==os.getuid() for p in (home,home/".config",units.parent,units))
    protected_home=home.stat().st_mode&0o077==0
    mode=units.stat().st_mode
    if units.resolve()!=units or not owned_tree or mode&0o002 or (mode&0o020 and not protected_home):
        raise RuntimeError("Expected the existing owner's unit directory")
    exists=managed_file(target,content)
    link=units/"default.target.wants"/UNIT
    if link.is_symlink() and link.resolve()!=target:
        raise RuntimeError("A separate watcher is already enabled")
    if link.exists() and not link.is_symlink():
        raise RuntimeError("Unexpected watcher enablement entry")
    if action=="rollback":
        if exists or link.is_symlink():
            ctl("disable","--now",UNIT)
            if exists:target.unlink()
            ctl("daemon-reload")
        if target.exists() or link.is_symlink():raise RuntimeError("Watcher rollback did not complete")
        return
    module=home/"bin/orangepi_model_review.py"
    if module.is_symlink() or hashlib.sha256(module.read_bytes()).hexdigest()!=expected:
        raise RuntimeError("Install the matching field review kit before the proposal watcher")
    if ctl("show","orangepi-ai-improvement.service","-p","LoadState","--value").stdout.strip()!="loaded":
        raise RuntimeError("Existing improvement worker unavailable")
    newly_created=not exists
    was_enabled=ctl("is-enabled",UNIT,check=False).returncode==0
    was_active=ctl("is-active",UNIT,check=False).returncode==0
    try:
        if newly_created:
            with tempfile.NamedTemporaryFile(dir=units,delete=False) as f:
                tmp=Path(f.name);os.fchmod(f.fileno(),0o600)
                f.write(content);f.flush();os.fsync(f.fileno())
            try:
                os.link(tmp,target)
            finally:tmp.unlink(missing_ok=True)
        ctl("daemon-reload")
        ctl("enable","--now",UNIT)
        if ctl("is-active",UNIT).stdout.strip()!="active" or ctl("is-enabled",UNIT).stdout.strip()!="enabled":
            raise RuntimeError("Watcher failed readback")
    except BaseException:
        if not was_active:ctl("stop",UNIT,check=False)
        if not was_enabled:ctl("disable",UNIT,check=False)
        if newly_created and managed_file(target,content):target.unlink()
        ctl("daemon-reload")
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("install","rollback"));a=p.parse_args()
    if os.getuid()==0:raise SystemExit("Run as the existing desktop owner")
    home=Path.home()
    # This independent install does not start, stop, or replace a model process.
    lock=home/".local/state/orangepi-review-wake-install.lock"
    lock.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"rb+") as f:
        s=os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid():raise RuntimeError("Unexpected install lock")
        fcntl.flock(f.fileno(),fcntl.LOCK_EX)
        deploy(home,a.action)
    print("Proposal watcher "+("enabled" if a.action=="install" else "removed"))


if __name__=="__main__":main()
