"""Install the field review window and menu entry for this desktop owner."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile


def put(path, contents, mode):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.resolve() != path.parent or path.parent.stat().st_uid != os.getuid():
        raise ValueError("Expected an owner-managed destination.")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            tmp = Path(f.name)
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
        tmp.chmod(mode)
        os.replace(tmp, path)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def files(home, source, notifications):
    payload = {}
    app = home/".local/share/orangepi-field-review"
    for name in ("field_change_review.py", "field_review_gtk.py"):
        payload[app/name] = ((source/name).read_bytes(), 0o600)
    launcher = home/".local/bin/orangepi-field-review"
    wrapper = "#!/bin/sh\nexec /usr/bin/python3 -B "+shlex.quote(str(app/"field_change_review.py"))+' "$@"\n'
    payload[launcher] = (wrapper.encode(), 0o700)
    target = str(launcher)
    if any(c in target for c in ("\r", "\n", "%", "$", "\\", '"', chr(96))):
        raise ValueError("Unsupported launcher path.")
    entry = "[Desktop Entry]\nType=Application\nName=Field change review\nComment=Review proposed controller and AI policy changes\n"
    payload[home/".local/share/applications/orangepi-field-review.desktop"] = (
        (entry+'Exec="'+target+'"\nTerminal=false\nIcon=preferences-system\nCategories=Settings;Utility;\n').encode(), 0o600)
    if notifications:
        payload[home/".config/autostart/orangepi-field-review-notify.desktop"] = (
            (entry+'Exec="'+target+'" --watch\nTerminal=false\nX-GNOME-Autostart-enabled=true\n').encode(), 0o600)
    return payload


def snapshot(path):
    try:
        meta = path.lstat()
    except FileNotFoundError:
        return None
    if (path.resolve()!=path or not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid()
            or meta.st_size>512*1024):
        raise ValueError("Unexpected installation file.")
    return [base64.b64encode(path.read_bytes()).decode(),stat.S_IMODE(meta.st_mode)]


def install(home, source, notifications=False, rollback=False):
    proposals = home/".local/state/corvon-maintenance/proposals"
    proposals.mkdir(mode=0o700, parents=True, exist_ok=True)
    if proposals.resolve()!=proposals or proposals.stat().st_mode & 0o077 or proposals.stat().st_uid!=os.getuid():
        raise ValueError("The controller proposal queue must be an owner-only directory.")
    state=home/".local/state/orangepi-field-review-install"
    state.mkdir(mode=0o700,parents=True,exist_ok=True)
    if state.resolve()!=state or state.stat().st_uid!=os.getuid() or state.stat().st_mode & 0o077:
        raise ValueError("Expected an owner-only installer state directory.")
    lock=os.open(state/"install.lock",os.O_RDWR|os.O_NOFOLLOW|os.O_CREAT,0o600)
    with os.fdopen(lock,"r+") as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        path=state/"rollback.json"
        # Paths are always constructed from the release allowlist, never from the journal.
        names={str(p.relative_to(home)):p for p in files(home,source,True)}
        current={n:snapshot(p) for n,p in names.items()}
        prior=snapshot(path)
        if prior:
            if prior[1]!=0o600:raise ValueError("Expected a private rollback journal.")
            saved=json.loads(base64.b64decode(prior[0]))
            if set(saved)!={"original","desired","previous"} or any(set(group)!=set(names) for group in saved.values()):
                raise ValueError("Unrecognized rollback journal.")
            if any(current[n] not in (saved["desired"][n],saved["previous"][n]) for n in names):
                raise ValueError("A local review file changed after installation. Inspect before replacing it.")
            original=saved["original"]
        elif rollback:
            return
        else:
            original=current.copy()
        if rollback:
            desired=original
        else:
            desired=current.copy()
            for p,(data,mode) in files(home,source,notifications).items():
                desired[str(p.relative_to(home))]=[base64.b64encode(data).decode(),mode]
        def save(previous):
            put(path,json.dumps(dict(original=original,desired=desired,previous=previous),sort_keys=True).encode(),0o600)
        save(current)
        for n,p in names.items():
            if current[n]==desired[n]:
                continue
            if desired[n] is None:
                p.unlink()
            else:
                data,mode=desired[n]
                put(p,base64.b64decode(data,validate=True),mode)
            if snapshot(p)!=desired[n]:raise OSError("Installation readback failed.")
        if rollback:
            path.unlink()
        else:
            save(desired)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notifications", action="store_true", help="Enable pending-proposal notifications at future logins")
    parser.add_argument("--rollback", action="store_true", help="Restore the exact previous reviewed application files")
    args = parser.parse_args()
    if os.getuid() == 0:
        raise SystemExit("Run as the ordinary desktop owner.")
    os.umask(0o077)
    install(Path.home(), Path(__file__).resolve().parent, args.notifications, args.rollback)
    print("Restored previous review files." if args.rollback else "Installed Field change review in the desktop application menu.")
