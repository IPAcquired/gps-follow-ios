"""Set or restore the desktop owner's GTK animation preference."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main(mode):
    os.umask(0o077)
    if not os.getuid():
        raise PermissionError("Use the desktop owner account")
    state=Path.home()/".local/state/paired-window-fit"
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    if state.is_symlink() or state.stat().st_uid!=os.getuid() or state.stat().st_mode&0o077:
        raise PermissionError("Owner state directory permissions differ")
    path=state/"gtk-animations.json"
    args=["xfconf-query","-c","xsettings","-p","/Gtk/EnableAnimations"]
    def get():
        r=subprocess.run(args,text=True,capture_output=True,timeout=4)
        if r.returncode==1 and "does not exist" in r.stderr:return None
        r.check_returncode()
        value=r.stdout.strip()
        if value not in ("true","false"):raise ValueError("GTK setting has an unexpected type.")
        return value
    before=get()
    if mode=="disable":
        if not path.exists():
            with path.open("x") as f:json.dump({"original":before},f)
        if before!="false":
            subprocess.run(args+(["-n","-t","bool"] if before is None else [])+["-s","false"],check=True)
        assert get()=="false"
    else:
        if not path.is_file() or path.is_symlink():raise ValueError("Missing saved preference")
        value=json.loads(path.read_text())["original"]
        if value not in (None,"true","false"):raise ValueError("Invalid saved preference")
        if before==value:return
        if before!="false":raise ValueError("The preference was changed independently")
        subprocess.run(args+(["-r"] if value is None else ["-s",value]),check=True)
        assert get()==value


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("disable","restore"));main(p.parse_args().mode)
