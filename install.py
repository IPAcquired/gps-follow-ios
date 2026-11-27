"""Install or restore the local health menu, indicator and login launcher."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile


def prior(path):
    if not path.exists() and not path.is_symlink():return None
    s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or path.resolve()!=path or s.st_size>1024*1024):
        raise ValueError("Unexpected installation file")
    return [base64.b64encode(path.read_bytes()).decode(),stat.S_IMODE(s.st_mode)]


def replace(path,record):
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    if path.parent.resolve()!=path.parent or path.parent.stat().st_uid!=os.getuid():
        raise ValueError("Expected an owner-managed directory")
    if record is None:
        path.unlink(missing_ok=True);return
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        f.write(base64.b64decode(record[0],validate=True));f.flush();os.fsync(f.fileno())
    name=Path(f.name);name.chmod(record[1]);os.replace(name,path)


def record(blob,mode=0o600):
    return [base64.b64encode(blob).decode(),mode]


def install(home,rollback=False):
    source=Path(__file__).resolve().parent
    dest=home/".local/share/orangepi-field-health";binary=home/".local/bin/orangepi-field-health"
    entry='[Desktop Entry]\nType=Application\nName=Pi health and sensors\nIcon=utilities-system-monitor\nTerminal=false\n'
    if any(c in str(binary) for c in ('"','%','\\',chr(96),'$','\n','\r')):raise ValueError("Unsupported desktop path")
    desired={dest/f:record((source/f).read_bytes()) for f in ("field_metrics.py","pi_health.py","health_corner.py")}
    desired[binary]=record(("#!/bin/sh\nexec /usr/bin/python3 -B "+shlex.quote(str(dest/"pi_health.py"))+' "$@"\n').encode(),0o700)
    desired[home/".local/share/applications/orangepi-field-health.desktop"]=record((entry+'Exec="'+str(binary)+'"\nCategories=System;Monitor;\n').encode())
    desired[home/".config/autostart/orangepi-field-health.desktop"]=record((entry+'Exec="'+str(binary)+'" --overlay\nX-GNOME-Autostart-enabled=true\n').encode())
    state=home/".local/state/orangepi-field-health";state.mkdir(parents=True,exist_ok=True,mode=0o700)
    if state.resolve()!=state or state.stat().st_uid!=os.getuid() or state.stat().st_mode&0o077:raise ValueError("Unexpected state directory")
    lockfd=os.open(state/"install.lock", os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(lockfd,"r+b") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        manifest=state/"install.json"; before={str(k.relative_to(home)):prior(k) for k in desired}
        target={str(k.relative_to(home)):v for k,v in desired.items()}
        if manifest.exists():
            saved=json.loads(base64.b64decode(prior(manifest)[0]))
            if set(before)!=set(saved["original"]) or saved["new"]!=target:raise ValueError("Use the matching installer for recovery")
            if any(v not in (saved["original"][k],target[k]) for k,v in before.items()):raise ValueError("A local file changed after installation")
        elif rollback:return
        else:
            saved={"original":before,"new":target}
            replace(manifest,record(json.dumps(saved,sort_keys=True).encode()))
        planned=saved["original"] if rollback else target
        for k,v in planned.items():
            if before[k]!=v:replace(home/k,v)
            if prior(home/k)!=v:raise OSError("Readback mismatch")
        if rollback:manifest.unlink()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--rollback",action="store_true");args=p.parse_args()
    if os.getuid()==0:raise SystemExit("Run as the graphical desktop owner.")
    os.umask(0o077);install(Path.home(),args.rollback)
    print("Restored previous menu files." if args.rollback else "Installed Pi health and sensors and its corner indicator.")
