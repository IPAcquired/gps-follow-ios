"""Install or roll back the intake on the reviewed native monitor. The operator restarts its service."""
import argparse
import hashlib
import os
from pathlib import Path
import pwd
import stat
import subprocess
import tempfile

from monitor_patch import BASE, patched


SOURCES=("onboard_postflight.py","postflight_store.py","postflight_summary.py","import_card.py")
PREVIEW_READERS={"b1c967332e4c6b9096ab4c45ed68deb9da9440a5e3f59b037f9071e1764ddc1c",
                 "98da6fabe3b87a24d072e48f1739139181541078240b95b1875d461da798a078"}
ANALYZER={"orangepi-bin-analyzer":"5b668c4c9e3f3195b7e81e4edaff2af03f05af50bdc843c9f981eb8345f07096",
          "flight_efficiency_metrics.py":"a55e0182b0962848c3fdae7789d17cb815c9b28209295499a70ee7df589f1be6",
          "battery_profile_store.py":"c32d7622360b575d347a1b8615a08b70b10e6a5bc2bbacdb5de119b1105861cc"}


def replace(path,data,mode):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
        temp=Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(),mode)
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:temp.unlink(missing_ok=True)


def install(action,root):
    monitor=root/"usr/local/bin/orangepi-mavlink-monitor"
    folder=root/"usr/local/lib/orangepi-postflight-intake"
    if monitor.is_symlink() or monitor.resolve()!=monitor or folder.resolve()!=folder:
        raise ValueError("Unexpected installation path")
    if not stat.S_ISREG(monitor.stat().st_mode) or monitor.stat().st_uid!=os.getuid():
        raise ValueError("Unexpected monitor owner or file type")
    stock_backup=folder/"monitor.original"
    raw=monitor.read_bytes()
    mode=stat.S_IMODE(monitor.stat().st_mode)
    stock=stock_backup.read_bytes() if stock_backup.exists() else raw
    if hashlib.sha256(stock).hexdigest()!=BASE:
        raise ValueError("Unknown baseline; no changes applied")
    desired=patched(stock)
    if raw not in (stock,desired):raise ValueError("Local monitor edits must be reviewed")
    if action=="check":
        return "active" if raw==desired else "stock"
    if action=="rollback":
        if raw!=stock:replace(monitor,stock,mode)
        return "stock"
    folder.mkdir(mode=0o755,parents=True,exist_ok=True)
    if folder.stat().st_uid!=os.getuid() or folder.stat().st_mode & 0o022:
        raise ValueError("Unexpected helper directory owner/mode")
    if not stock_backup.exists():replace(stock_backup,stock,0o600)
    for name in SOURCES:
        path=folder/name
        expected=Path(__file__).with_name(name).read_bytes()
        if path.exists():
            existing=path.read_bytes()
            recognized=(name=="onboard_postflight.py" and hashlib.sha256(existing).hexdigest() in PREVIEW_READERS)
            if path.is_symlink() or (existing!=expected and not recognized):
                raise ValueError("Existing helper differs: "+name)
    for name in SOURCES:
        path=folder/name
        expected=Path(__file__).with_name(name).read_bytes()
        if not path.exists() or path.read_bytes()!=expected:replace(path,expected,0o644)
    if raw!=desired:replace(monitor,desired,mode)
    return "active"


def service_setup(action,root,home,uid,gid):
    # /home is still a private tmpfs. The monitor can see only these two already-private data trees.
    if home.resolve()!=home or any(not part or not all(c.isalnum() or c in "._-" for c in part)
                                   for part in home.parts[1:]):
        raise ValueError("Unsupported owner home path")
    base=root/"usr/local/lib/orangepi-postflight-intake"
    drop=root/"etc/systemd/system/orangepi-mavlink-monitor.service.d/82-postflight-intake.conf"
    data=home/"flight-data"
    private=(data/"inbox",data/"acquisition")
    cfg=("[Service]\nProtectHome=tmpfs\n"+"".join("BindPaths="+str(path)+"\n" for path in private)
         +"Environment=PYTHONNOUSERSITE=1\n").encode()
    if drop.resolve()!=drop or (drop.exists() and drop.read_bytes()!=cfg):
        raise ValueError("Local monitor service override needs manual review")
    if action=="rollback":
        result=install(action,root)
        if drop.exists():drop.unlink()
        return result
    if action=="check":return install(action,root)
    if data.resolve()!=data or data.stat().st_uid!=uid or data.stat().st_mode&0o077:
        raise ValueError("Unexpected flight data storage owner/mode")
    for path in private:
        if not path.exists():
            if path.name!="acquisition":raise ValueError("Existing inbox required")
            path.mkdir(mode=0o700)
            os.chown(path,uid,gid)
        if path.resolve()!=path or not path.is_dir() or path.stat().st_uid!=uid or path.stat().st_mode&0o077:
            raise ValueError("Expected private data directories")
    contents={}
    for name,digest in ANALYZER.items():
        src=home/"bin"/name
        contents[name]=src.read_bytes()
        if hashlib.sha256(contents[name]).hexdigest()!=digest:
            raise ValueError("Unknown installed analyzer file: "+name)
    # Keep all executed code immutable within the service, including the established analyzer.
    result=install(action,root)
    copy=base/"analyzer"
    copy.mkdir(mode=0o755,exist_ok=True)
    if copy.resolve()!=copy or copy.stat().st_uid!=os.getuid() or copy.stat().st_mode&0o022:
        raise ValueError("Unexpected analyzer installation directory")
    for name,content in contents.items():
        target=copy/name
        if target.exists() and (target.is_symlink() or target.read_bytes()!=content):
            raise ValueError("Pinned analyzer copy differs: "+name)
        if not target.exists():replace(target,content,0o644)
    drop.parent.mkdir(parents=True,exist_ok=True)
    if not drop.exists():replace(drop,cfg,0o644)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("check","activate","rollback"))
    args=parser.parse_args()
    owner=subprocess.check_output(["systemctl","show","orangepi-mavlink-monitor.service",
                                   "-p","User","--value"],text=True).strip()
    account=pwd.getpwnam(owner)
    if account.pw_uid==0:raise ValueError("Expected unprivileged monitor account")
    print(service_setup(args.action,Path("/"),Path(account.pw_dir),account.pw_uid,account.pw_gid))
