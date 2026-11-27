"""Install a checked private release and atomically hand the owner launcher to it."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
UNIT="orange-pi-wired-desktop-discovery.service"

def owned(path,private=False):
    s=path.lstat()
    return s.st_uid==os.getuid() and not stat.S_ISLNK(s.st_mode) and (not private or (s.st_mode & 0o077)==0)

def atomic_link(path,target):
    tmp=path.with_name(".new-"+secrets.token_hex(8))
    try:
        tmp.symlink_to(os.path.relpath(target,path.parent));os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def replace_bytes(path,data):
    tmp=path.with_name(".new-"+secrets.token_hex(8))
    try:
        fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as f:f.write(data)
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)

def service(*args,must=True):
    env=os.environ.copy();env["XDG_RUNTIME_DIR"]="/run/user/"+str(os.getuid())
    r=subprocess.run(["/usr/bin/systemctl","--user",*args],env=env,text=True,capture_output=True,timeout=20)
    if must and r.returncode:raise RuntimeError("Owner service manager declined "+args[0]+".")
    return r

def main(run):
    os.umask(0o077)
    if os.getuid()==0 or not owned(HERE,True):raise PermissionError("Use the existing owner account.")
    manifest=json.loads((HERE/"sha256.json").read_text())
    assert set(manifest)>={"direct_usb.py","pair_channel.py","auto_service.py","launch","discovery.service"}
    immutable=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:16]
    home=Path.home();base=home/".local/share/orange-pi-wired-desktop"
    releases=base/"releases";release=releases/("paired-"+immutable)
    bin_dir=home/".local/bin";current=base/"current";launcher=bin_dir/"orange-pi-wired-desktop"
    units=home/".config/systemd/user";units.mkdir(mode=0o700,parents=True,exist_ok=True)
    unit=units/UNIT
    if not all(owned(p) for p in (home,bin_dir,units)):raise PermissionError("Owner directory declined.")
    for path in (base,releases):
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        assert owned(path,True)
    payload={}
    for name,digest in manifest.items():
        assert name==Path(name).name and owned(HERE/name,True)
        data=(HERE/name).read_bytes();assert hashlib.sha256(data).hexdigest()==digest
        payload[name]=data
    with open(base/".install.lock","a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not release.exists():
            with tempfile.TemporaryDirectory(prefix=".incoming-",dir=releases) as incoming:
                build=Path(incoming)/"release";build.mkdir(mode=0o700)
                for name,data in payload.items():
                    file=build/name;file.write_bytes(data);file.chmod(0o700 if name=="launch" else 0o600)
                verify(build)
                build.rename(release)
        else:
            assert owned(release,True)
            for name,data in payload.items():
                assert owned(release/name,True) and (release/name).read_bytes()==data
            verify(release)
        if not run:
            print("Release staged and tests passed.");return
        old_launcher=launcher.resolve(strict=True) if os.path.lexists(launcher) else None
        if old_launcher:assert launcher.is_symlink() and old_launcher.name=="launch" and old_launcher.parent.parent==releases
        old_current=current.resolve(strict=True) if os.path.lexists(current) else None
        if old_current:assert current.is_symlink() and old_current.parent==releases
        old_unit=unit.read_bytes() if unit.exists() else None
        if old_unit:assert owned(unit,True) and b"Description=Locally paired Orange Pi touchscreen" in old_unit
        initially_active=service("is-active",UNIT,must=False).returncode==0
        initially_enabled=service("is-enabled",UNIT,must=False).returncode==0
        try:
            # A service restart closes its sole CDC handle before starting the new version.
            if initially_active:service("stop",UNIT)
            atomic_link(current,release);atomic_link(launcher,current/"launch")
            replace_bytes(unit,payload["discovery.service"])
            service("daemon-reload");service("enable","--now",UNIT)
            assert service("is-active",UNIT).stdout.strip()=="active"
            assert service("is-enabled",UNIT).stdout.strip()=="enabled"
            guard=service("show",UNIT,"-p","RestrictAddressFamilies","--value").stdout.strip()
            assert guard=="AF_UNIX"
        except Exception:
            service("stop",UNIT,must=False)
            if not initially_enabled:service("disable",UNIT,must=False)
            if old_launcher:atomic_link(launcher,old_launcher)
            else:launcher.unlink(missing_ok=True)
            if old_current:atomic_link(current,old_current)
            else:current.unlink(missing_ok=True)
            if old_unit:replace_bytes(unit,old_unit)
            else:unit.unlink(missing_ok=True)
            service("daemon-reload",must=False)
            if initially_active:service("start",UNIT,must=False)
            raise
        print("Paired service enabled, active, local-only and verified.")

def verify(root):
    names=sorted(p.stem for p in root.glob("test_*.py"))
    r=subprocess.run([sys.executable,"-B","-m","unittest","-q",*names],cwd=root,text=True,capture_output=True,timeout=90)
    if r.returncode:
        print(r.stderr[-2800:]);raise RuntimeError("Release verification failed.")
    for line in r.stderr.splitlines():
        if line.startswith("Ran "):print(line)
    assert subprocess.run([str(root/"launch"),"--help"],capture_output=True,timeout=8).returncode==0

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("stage","activate"));main(p.parse_args().mode=="activate")
