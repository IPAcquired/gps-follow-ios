#!/usr/bin/python3
"""Apply or restore the owner-local GTK layout for the supported field-review release."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

BASE_SHA = "e6c7938cd1af78e8d71da6a5e020fd18a14b48c8572f44c816b5c76c3338a058"
LAYOUT_SHA = "d0a5ece6128789b897ca6a7645505739cea2e5b06cf0018eafa6f7a2ab80280a"
PATCH_SHA = "0e545f40edb658a7b900d59748f2a1f93f0b0265131453b555537e041f68bf33"
HERE=Path(__file__).resolve().parent
UI_REL=".local/share/orangepi-field-review/field_review_gtk.py"
UPSTREAM_NAMES={UI_REL, ".local/share/orangepi-field-review/field_change_review.py",
                ".local/bin/orangepi-field-review", ".local/share/applications/orangepi-field-review.desktop",
                ".config/autostart/orangepi-field-review-notify.desktop"}

def check(ok, message):
    if not ok:
        raise ValueError(message)

def digest(body):
    return hashlib.sha256(body).hexdigest()

def encode(body,mode):
    return [base64.b64encode(body).decode("ascii"),mode]

def data(record):
    return base64.b64decode(record[0],validate=True)

def snapshot(path,limit=512*1024):
    if not os.path.lexists(path):
        return None
    props=path.lstat()
    check(path.resolve()==path and stat.S_ISREG(props.st_mode) and props.st_uid==os.getuid() and
          props.st_size<=limit,"Unexpected file at "+path.name)
    return encode(path.read_bytes(),stat.S_IMODE(props.st_mode))

def put(path,record):
    check(path.parent.resolve()==path.parent and path.parent.stat().st_uid==os.getuid(),"Unexpected owner directory")
    if record is None:
        path.unlink(missing_ok=True)
        return
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
            tmp=Path(f.name)
            f.write(data(record))
            os.fchmod(f.fileno(),record[1])
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)

def candidate(original):
    body=data(original)
    check(original[1]==0o600 and digest(body)==BASE_SHA,"Installed GTK source differs from the supported release")
    patch=(HERE/"layout.json").read_bytes()
    check(digest(patch)==PATCH_SHA,"Kit layout patch changed")
    lines=body.decode("utf-8").splitlines(keepends=True)
    new=[]
    pos=0
    for edit in json.loads(patch):
        start,end,added=edit
        check(type(start) is int and type(end) is int and pos<=start<=end<=len(lines)
              and isinstance(added,str),"Invalid patch range")
        new.extend(lines[pos:start])
        new.append(added)
        pos=end
    contents=("".join(new)+"".join(lines[pos:])).encode()
    check(digest(contents)==LAYOUT_SHA,"Reconstructed GTK source differs from the verified layout")
    compile(contents,"field_review_gtk.py","exec")
    return encode(contents,original[1])

def journal_after(before,original,desired):
    if before is None:
        return None
    check(before[1]==0o600,"Upstream journal must be owner-only")
    parent=json.loads(data(before))
    check(set(parent)=={"original","desired","previous"} and all(isinstance(v,dict) and set(v)==UPSTREAM_NAMES
         for v in parent.values()),"Unrecognized field-review rollback journal")
    check(parent["desired"][UI_REL]==original and parent["previous"][UI_REL]==original,
          "The previous GTK installer has an unfinished or different revision")
    parent["desired"][UI_REL]=desired
    parent["previous"][UI_REL]=desired
    return encode(json.dumps(parent,sort_keys=True).encode(),0o600)

def process(home,action):
    check(os.getuid()!=0,"Run from the ordinary desktop owner account")
    os.umask(0o077)
    target=home/UI_REL
    state=home/".local/state/orangepi-field-review-install"
    parentfile=state/"rollback.json"
    backup=state/"optional-layout-v1.json"
    if not state.exists():
        if action=="rollback":
            return {"state":"no saved layout installation"}
        if action=="status":
            current=snapshot(target)
            return {"state":"original" if current and digest(data(current))==BASE_SHA else "not installed or different"}
        check(target.is_file(),"Install the supported field review first")
        state.mkdir(parents=True,mode=0o700)
    meta=state.lstat()
    check(state.resolve()==state and stat.S_ISDIR(meta.st_mode) and meta.st_uid==os.getuid() and not meta.st_mode&0o077,
          "Unexpected field-review installer state directory")
    fd=os.open(state/"install.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    with os.fdopen(fd,"r+") as lock:
        props=os.fstat(lock.fileno())
        check(stat.S_ISREG(props.st_mode) and props.st_uid==os.getuid() and not props.st_mode&0o077,"Unexpected installer lock")
        fcntl.flock(lock,fcntl.LOCK_EX)
        current=snapshot(target)
        parent=snapshot(parentfile)
        saved=snapshot(backup,2*1024*1024)
        if saved is None:
            if action=="rollback":
                return {"state":"no saved layout installation"}
            if action=="status":
                return {"state":"original" if current and digest(data(current))==BASE_SHA else "not installed or different"}
            check(current is not None,"The original GTK app must already be installed")
            original,prior=current,parent
        else:
            check(saved[1]==0o600,"Expected owner-only layout restore journal")
            record=json.loads(data(saved))
            check(set(record)=={"schema","original_ui","original_upstream_journal"} and record["schema"]==1,
                  "Unrecognized layout restore journal")
            original,prior=record["original_ui"],record["original_upstream_journal"]
        after=candidate(original)
        next_parent=journal_after(prior,original,after)
        check(current in (original,after) and parent in (prior,next_parent),
              "Preserving a field-review file or journal changed since staging")
        if action=="status":
            return {"state":"installed" if current==after and parent==next_parent else "incomplete"}
        if saved is None:
            body=json.dumps({"schema":1,"original_ui":original,"original_upstream_journal":prior},sort_keys=True).encode()
            put(backup,encode(body,0o600))
        undo=action=="rollback"
        wanted_ui,wanted_parent=(original,prior) if undo else (after,next_parent)
        for path,was,want in ((target,current,wanted_ui),(parentfile,parent,wanted_parent)):
            if was!=want:
                check(snapshot(path)==was,"Concurrent edit detected")
                put(path,want)
                check(snapshot(path)==want,"Readback differed from source")
        if undo:
            backup.unlink()
        return {"state":"restored" if undo else "installed","gtk_sha256":digest(data(wanted_ui))}

if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("action",nargs="?",default="install",choices=("install","status","rollback"))
    cli.add_argument("--rollback",action="store_true",help="restore original UI and exact original installer journal")
    args=cli.parse_args()
    print(json.dumps(process(Path.home(),"rollback" if args.rollback else args.action)))

