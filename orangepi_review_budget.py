"""Bound the two 4B services only while a proposal review owns the existing model lock."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import select
import shlex
import subprocess
import sys
import time

HEAVY=("orangepi-ai-quality.service","orangepi-ai-long.service")
FAST="orangepi-ai.service"
CAP=b"[Service]\nEnvironment=AI_THREADS=2\nCPUQuota=150%\n"


def budget(unit):
    if unit==HEAVY[0]:
        return CAP+b"Environment=LLAMA_ARG_BATCH=256 LLAMA_ARG_UBATCH=64\n"
    return CAP


def run(*args,check=True):
    return subprocess.run(args,capture_output=True,text=True,check=check,timeout=30).stdout.strip()


def ctl(*args,check=True):
    return run("systemctl","--user",*args,check=check)


def setting(unit,key):
    return ctl("show",unit,"-p",key,"--value")


def state_root():
    runtime=Path(os.environ["XDG_RUNTIME_DIR"])
    if runtime.resolve()!=runtime or runtime.stat().st_uid!=os.getuid():
        raise RuntimeError("Invalid local runtime directory")
    folder=runtime/"orangepi-review-budget"
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.resolve()!=folder or folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:
        raise RuntimeError("Invalid review runtime directory")
    return folder


def startmark(pid):
    # comm may contain spaces and parentheses. starttime is field 22.
    return (Path("/proc")/str(pid)/"stat").read_text().rsplit(")",1)[1].split()[19]


def unit_files(root,token):
    if not re.fullmatch("[a-f0-9]{32}",token):
        raise RuntimeError("Invalid budget lease")
    return [root.parent/"systemd/user"/(u+".d")/("zzzz-field-review-"+token+".conf") for u in HEAVY]


def exclusive(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())


def is_active(unit):
    return ctl("is-active",unit,check=False) in ("active","activating","deactivating")


def checked_settings(capped):
    for unit in HEAVY:
        env=shlex.split(setting(unit,"Environment"))
        threads=[s for s in env if s.startswith("AI_THREADS=")]
        if threads!=["AI_THREADS="+("2" if capped else "8")]:
            raise RuntimeError("Unexpected model service thread setting")
        if setting(unit,"CPUQuotaPerSecUSec")!=("1.500000s" if capped else "infinity"):
            raise RuntimeError("Unexpected model service CPU quota")
        if unit==HEAVY[0]:
            sizes={s for s in env if s.startswith(("LLAMA_ARG_BATCH=","LLAMA_ARG_UBATCH="))}
            if sizes!=({"LLAMA_ARG_BATCH=256","LLAMA_ARG_UBATCH=64"} if capped else set()):
                raise RuntimeError("Unexpected model batch setting")


def finish(folder,record,team):
    token=record["token"];lease=folder/"lease.json"
    if not lease.exists() or json.loads(lease.read_bytes())!=record:
        return
    # Recovery may follow process termination at any individual file operation.
    for unit in HEAVY:
        if is_active(unit):
            ctl("stop",unit)
    for unit,p in zip(HEAVY,unit_files(folder,token)):
        if p.exists():
            if p.is_symlink() or p.read_bytes()!=budget(unit):raise RuntimeError("Review override changed")
            p.unlink()
            try:p.parent.rmdir()
            except OSError:pass
    ctl("daemon-reload")
    checked_settings(False)
    if record["fast"]:
        if not is_active(FAST):ctl("start",FAST)
        team["wait_healthy"](team["PROFILES"][0],90)
    lease.unlink()
    (folder/(token+".ready")).unlink(missing_ok=True)


def watch(token):
    folder=state_root();lease=folder/"lease.json"
    record=json.loads(lease.read_bytes())
    if record.get("token")!=token or not re.fullmatch("[a-f0-9]{32}",token):
        raise RuntimeError("Unknown review owner")
    poller=select.poll()
    fd=None
    try:
        try:
            fd=os.pidfd_open(record["pid"])
            if startmark(record["pid"])!=record["start"]:raise ProcessLookupError
            poller.register(fd,select.POLLIN)
            exclusive(folder/(token+".ready"),b"ready\n")
            while lease.exists():
                if json.loads(lease.read_bytes())!=record:return
                if poller.poll(500):break
            else:return
        except (ProcessLookupError,FileNotFoundError):
            pass
    finally:
        if fd is not None:os.close(fd)
    team=runpy.run_path(str(Path(__file__).resolve().with_name("orangepi-ai-team")))
    while lease.exists():
        try:lock=team["acquire_orchestration_lock"]()
        except BlockingIOError:
            time.sleep(.5);continue
        with lock:
            finish(folder,record,team)
        return


@contextmanager
def capped_services(team):
    # The caller already holds the orchestrator flock, including during recovery.
    folder=state_root();lease=folder/"lease.json"
    if lease.exists():
        old=json.loads(lease.read_bytes())
        try:owner_alive=startmark(old["pid"])==old["start"]
        except (FileNotFoundError,ProcessLookupError):owner_alive=False
        if owner_alive:raise RuntimeError("Another maintenance review is in progress")
        finish(folder,old,team)
    active=[p.service for p in team["PROFILES"] if is_active(p.service)]
    if active not in ([],[FAST]):raise RuntimeError("Another model profile is active")
    checked_settings(False)
    token=secrets.token_hex(16);pid=os.getpid()
    record=dict(token=token,pid=pid,start=startmark(pid),fast=FAST in active)
    exclusive(lease,json.dumps(record).encode())
    try:
        # The detached watcher owns no model service. If this process dies, it
        # takes the original lock and restores the exact profile and unit state.
        run("systemd-run","--user","--collect","--quiet","--unit=orangepi-review-recover-"+token,
            "--property=UMask=0077","--property=RuntimeMaxSec=35min",sys.executable,"-B",
            str(Path(__file__).resolve()),"watch",token)
        ready=folder/(token+".ready")
        end=time.monotonic()+10
        while not ready.exists() and time.monotonic()<end:time.sleep(.05)
        if not ready.exists():raise RuntimeError("Independent model recovery unavailable")
        for unit,f in zip(HEAVY,unit_files(folder,token)):
            f.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if f.parent.resolve()!=f.parent or f.parent.stat().st_uid!=os.getuid():
                raise RuntimeError("Unexpected runtime unit directory")
            exclusive(f,budget(unit))
        ctl("daemon-reload");checked_settings(True)
        yield
    finally:
        finish(folder,record,team)


if __name__=="__main__":
    if len(sys.argv)!=3 or sys.argv[1]!="watch":raise SystemExit(2)
    watch(sys.argv[2])
