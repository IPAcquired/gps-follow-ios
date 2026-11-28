#!/usr/bin/python3
"""Check, install or restore the failed-service age correction in the display publisher."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import tempfile
import time

NAME="display_telemetry.py"
UNIT="orangepi-companion.service"
PRE="359ed80c45cb601c6b9caa6fd4b197400815ccf6ec47fc2c8e5f135f53dc5e7a"
POST="73aa283911eced1ac5219166b3ee792be136034e6e443ebed02601a50cadfc3e"
HERE=Path(__file__).resolve().parent

def ensure(value,message):
    if not value:raise ValueError(message)

def sha(body):return hashlib.sha256(body).hexdigest()

def unit_state():
    out=subprocess.run(["systemctl","--user","show",UNIT,"-p","LoadState","-p","ActiveState","-p","MainPID"],
                       check=True,capture_output=True,text=True,timeout=15)
    fields=dict(line.split("=",1) for line in out.stdout.splitlines() if "=" in line)
    ensure(fields.get("LoadState")=="loaded","Existing publisher user unit is unavailable")
    return fields["ActiveState"],int(fields.get("MainPID",0))

def restart():
    subprocess.run(["systemctl","--user","restart",UNIT],check=True,timeout=40)
    ensure(unit_state()[0]=="active","Updated publisher did not become active")

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def write(path,body,mode,gid=None):
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
            temporary=Path(f.name)
            if gid is not None and os.fstat(f.fileno()).st_gid!=gid:os.fchown(f.fileno(),-1,gid)
            os.fchmod(f.fileno(),mode);f.write(body);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path);sync_dir(path.parent)
    finally:
        if temporary:temporary.unlink(missing_ok=True)

def module(path):
    ensure(path.resolve()==path,"Unexpected publisher path")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,"rb") as f:
        meta=os.fstat(f.fileno());mode=stat.S_IMODE(meta.st_mode)
        ensure(stat.S_ISREG(meta.st_mode) and meta.st_uid==os.getuid() and not mode&0o022
               and meta.st_size<=1024*1024,"Unexpected module type, size, ownership or mode")
        return f.read(),mode,meta.st_gid

def delta(original):
    ensure(sha(original)==PRE,"Installed publisher differs from the qualified source")
    change=json.loads((HERE/"service-clock-edits.json").read_bytes())
    ensure((change["name"],change["before"],change["after"])==(NAME,PRE,POST),"Unsupported patch manifest")
    lines=original.decode().splitlines(keepends=True);new=[];pos=0
    for item in change["edits"]:
        start,end=item["start"],item["end"]
        ensure(pos<=start<=end<=len(lines) and "".join(lines[start:end])==item["before"],"Hunk preimage mismatch")
        new.extend(lines[pos:start]);new.append(item["after"]);pos=end
    new.extend(lines[pos:]);body="".join(new).encode()
    ensure(sha(body)==POST,"Postimage hash mismatch")
    compile(body,NAME,"exec")
    return body

def state_dir(path):
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    m=path.lstat()
    ensure(path.resolve()==path and stat.S_ISDIR(m.st_mode) and m.st_uid==os.getuid() and
           stat.S_IMODE(m.st_mode)==0o700,"Expected private owner state directory")

def load_backup(p):
    if not os.path.lexists(p):return None
    b,mode,_=module(p)
    ensure(mode==0o600,"Expected private backup record")
    r=json.loads(b)
    ensure(r.get("schema")==1 and sha(base64.b64decode(r["original"],validate=True))==PRE
           and r.get("phase") in ("installing","installed","restoring") and type(r["restart_active"]) is bool,"Invalid backup")
    return r

def save(p,r):write(p,(json.dumps(r,sort_keys=True)+"\n").encode(),0o600)

def erase(p):
    p.unlink();sync_dir(p.parent)

def update(action,home,service_state=unit_state,service_restart=restart):
    uid=os.getuid();ensure(uid!=0,"Run as the graphical desktop owner")
    os.umask(0o077)
    folder=home/"bin";target=folder/NAME;state=home/".local/state/orangepi-display-service-clock";backup=state/"original.json"
    fd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        meta=os.fstat(fd)
        ensure(folder.resolve()==folder and meta.st_uid==uid and not meta.st_mode&0o022,"Unsafe owner bin directory")
        fcntl.flock(fd,fcntl.LOCK_SH if action=="check" else fcntl.LOCK_EX)
        now,mode,gid=module(target);key=sha(now)
        if os.path.lexists(state): state_dir(state)
        entry=load_backup(backup)
        if action=="check":
            return {"module":"original" if key==PRE else "installed" if key==POST else "different",
                    "module_sha256":key,"mode":oct(mode),"backup_phase":entry["phase"] if entry else None,
                    "unit":UNIT,"unit_state":service_state()[0]}
        ensure(key in (PRE,POST),"Local publisher differs from both supported revisions; preserving it")
        if entry is None and action=="restore" and key==PRE:
            return {"module":"original","changed":False,"service_restarted":False}
        if entry:
            ensure(entry["uid"]==uid and entry["gid"]==gid and entry["mode"]==mode,"Publisher metadata changed; preserving it")
            original=base64.b64decode(entry["original"],validate=True)
            if action=="install" and key==POST and entry["phase"]=="installed":
                return {"module":"installed","changed":False,"service_restarted":False}
        else:
            ensure(key==PRE and action=="install","Original private backup missing")
            original=now
        after=delta(original)
        active,_=service_state()
        ensure(active in ("active","inactive","failed"),"Wait for the current publisher service transition")
        expect_active=active=="active" or bool(entry and entry["phase"]!="installed" and entry["restart_active"])
        if entry is None:
            state_dir(state)
            entry={"schema":1,"uid":uid,"gid":gid,"mode":mode,"original":base64.b64encode(original).decode("ascii")}
        entry.update(phase="installing" if action=="install" else "restoring",restart_active=expect_active)
        save(backup,entry)
        desired=after if action=="install" else original
        rollback=original if action=="install" else after
        try:
            if now!=desired:
                ensure(module(target)==(now,mode,gid),"Publisher changed during update")
                write(target,desired,mode,gid)
            ensure(module(target)==(desired,mode,gid),"Publisher readback failed")
            if expect_active:service_restart()
        except BaseException:
            seen,sm,sg=module(target)
            ensure(seen in (desired,rollback) and (sm,sg)==(mode,gid),"External module edit detected; preserving it")
            if seen!=rollback:write(target,rollback,mode,gid)
            ensure(module(target)==(rollback,mode,gid),"Rollback readback failed")
            if expect_active:service_restart()
            if action=="install":erase(backup)
            else:
                entry.update(phase="installed");save(backup,entry)
            raise
        if action=="restore":
            erase(backup)
        else:
            entry.update(phase="installed");save(backup,entry)
        return {"module":"installed" if action=="install" else "original","module_sha256":sha(desired),
                "changed":now!=desired,"service_restarted":expect_active}
    finally:os.close(fd)

def status_sample():
    path=Path("/run/user")/str(os.getuid())/"axl-display-bridge/snapshot.sock"
    m=path.lstat()
    ensure(path.resolve()==path and stat.S_ISSOCK(m.st_mode) and m.st_uid==os.getuid() and
           not stat.S_IMODE(m.st_mode)&0o077,"Unexpected private display status socket")
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
        peer.settimeout(6);peer.connect(str(path))
        _,uid,_=struct.unpack("3i",peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        ensure(uid==os.getuid(),"Unexpected status publisher")
        peer.sendall(b"snapshot\n")
        with peer.makefile("rb") as stream:raw=stream.read(65537)
    ensure(len(raw)<=65536,"Oversized read-only status")
    d=json.loads(raw);s=d.get("pi_service_health",{})
    ensure(d.get("schema")==1 and d.get("flight_control_authority") is False and d.get("mavlink_transmit") is False,
           "Unexpected read-only snapshot schema")
    age=s.get("age_ms");units=s.get("units")
    ensure((age is None or type(age) is int and 0<=age<=86400000) and isinstance(units,list),"Invalid service inventory")
    return {"age_ms":age,"fresh":s.get("fresh") is True,"sample_succeeded":s.get("sample_succeeded") is True,
            "listed_unit_count":len(units),"source":s.get("source")=="bounded_failed_service_inventory"}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=("check","install","restore"))
    p.add_argument("--live",action="store_true",help="also sample only service inventory fields from the existing local read-only bridge")
    p.add_argument("--samples",type=int,default=3);a=p.parse_args()
    ensure(1<=a.samples<=10,"Use 1 through 10 samples")
    report=update(a.action,Path.home())
    if a.live:
        results=[]
        for i in range(a.samples):
            if i:time.sleep(.6)
            results.append(status_sample())
        report["service_inventory"]=results
    print(json.dumps(report,sort_keys=True))

