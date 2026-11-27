"""Install or restore the headless XFCE window-fitting fix using an exact source preimage."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import stat
import subprocess

OLD_SHA="c3e4184ed05805cff76374189cbe640ad904a577a92cce8f9a67acd6086d7dee"
OLD_BLOCK="""                kind=command(['xprop','-id',window,'_NET_WM_WINDOW_TYPE']).stdout
                if '_NET_WM_WINDOW_TYPE_NORMAL' in kind:
                    command(['wmctrl','-i','-r',hex(int(window)),'-b','remove,maximized_vert,maximized_horz'])
                    command(['wmctrl','-i','-r',hex(int(window)),'-e',f'0,0,27,{_size[0]},{max(150,_size[1]-52)}'])
                    command(['wmctrl','-i','-r',hex(int(window)),'-b','add,maximized_vert,maximized_horz'])"""
NEW_BLOCK="""                properties=command(['xprop','-id',window,'_NET_WM_WINDOW_TYPE','_NET_WM_STATE']).stdout
                maximized=all(flag in properties for flag in ('_NET_WM_STATE_MAXIMIZED_VERT','_NET_WM_STATE_MAXIMIZED_HORZ'))
                if '_NET_WM_WINDOW_TYPE_NORMAL' not in properties or '_NET_WM_STATE_FULLSCREEN' in properties or maximized:
                    continue
                if re.search(r'^\\S+ connected(?: primary)? ',command(['xrandr','--current']).stdout,re.M):
                    continue
                command(['wmctrl','-i','-r',hex(int(window)),'-b','add,maximized_vert,maximized_horz'])"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def revised(prior):
    if sha(prior)!=OLD_SHA or prior.count(OLD_BLOCK.encode())!=1:
        raise ValueError("The existing desktop workspace helper requires independent review.")
    return prior.replace(OLD_BLOCK.encode(),NEW_BLOCK.encode())


def replace(path,data):
    original=path.lstat()
    if not stat.S_ISREG(original.st_mode) or original.st_uid!=os.getuid() or original.st_mode&0o022:
        raise PermissionError("Expected an existing owner-controlled helper")
    tmp=path.with_name(".fit-update-"+secrets.token_hex(8))
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(data);os.fchmod(f.fileno(),stat.S_IMODE(original.st_mode));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def main(mode):
    os.umask(0o077)
    if not os.getuid():raise PermissionError("Use the desktop owner's account.")
    path=Path.home()/"bin/desktop_workspace.py"
    state=Path.home()/".local/state/paired-window-fit"
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    st=state.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077:
        raise PermissionError("Owner state directory permissions differ")
    backup=state/"original.py"
    if not backup.exists():
        prior=path.read_bytes()
        revised(prior)
        with backup.open("xb") as out:out.write(prior)
    meta=backup.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid() or meta.st_mode&0o077:
        raise PermissionError("Owner backup permissions differ")
    prior=backup.read_bytes()
    new=revised(prior)
    current=path.read_bytes()
    if current not in (prior,new):raise ValueError("The workspace helper changed after staging")
    target=new if mode=="install" else prior
    if current==target:return
    compile(target,str(path),"exec")
    replace(path,target)
    service=["systemctl","--user","restart","orangepi-companion.service"]
    try:
        subprocess.run(service,check=True,timeout=25)
        assert subprocess.run(["systemctl","--user","is-active","--quiet",service[-1]]).returncode==0
    except BaseException:
        replace(path,current)
        subprocess.run(service,timeout=25)
        raise
    print("Window fitting updated and the companion service is active.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("install","restore"))
    main(p.parse_args().mode)
