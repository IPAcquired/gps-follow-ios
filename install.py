"""Install or restore the optional same-owner AI team context bridge."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile


BASE="01cc7827d39d381471754dae0ebf7aceebe3f473461af72fbc21ff91593c44c5"
MODULE="orangepi_postflight_evidence.py"
PREVIEW="f9931f4e6ead8ec42adaed02983019d263a136b3da096cb1e1e1e196d6f6f684"


def patched(raw):
    if hashlib.sha256(raw).hexdigest()!=BASE:raise ValueError("Unsupported AI-team version")
    text=raw.decode()
    def change(old,new):
        nonlocal text
        if text.count(old)!=1:raise ValueError("Unexpected AI-team source")
        text=text.replace(old,new)
    change("    verified_facts: str,\n) -> str:\n    from orangepi_model_review import telemetry",
           "    verified_facts: str,\n    local_observations: str = '{}',\n) -> str:\n    from orangepi_model_review import telemetry")
    change('        "LIVE LOCAL CONTROLLER MONITOR (missing fields',
           '        "LOCAL CACHED DATAFLASH OBSERVATIONS (historical or provisional, never approval, live state, or evidence of a flown sortie):\\n"\n'
           '        + local_observations + "\\n\\n"\n        "LIVE LOCAL CONTROLLER MONITOR (missing fields')
    change("    flight_context = approved_context()\n",
           "    flight_context = approved_context()\n"
           "    from orangepi_postflight_evidence import model_context\n"
           "    local_observations = json.dumps(model_context(),sort_keys=True,separators=(',',':'))\n")
    change("                question, outputs, profile.name, flight_context, verified_facts\n",
           "                question, outputs, profile.name, flight_context, verified_facts, local_observations\n")
    compile(text,"orangepi-ai-team","exec")
    return text.encode()


def replace(path,value,mode):
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as dest:
        tmp=Path(dest.name)
        try:
            os.fchmod(dest.fileno(),mode)
            dest.write(value);dest.flush();os.fsync(dest.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:tmp.unlink(missing_ok=True)


def setup(home,action):
    folder=home/"bin"
    team=folder/"orangepi-ai-team"
    mod=folder/MODULE
    storage=home/".local/state/orangepi-postflight-evidence"
    backup=storage/"team.original"
    for path in (team,mod,backup):
        if path!=path.resolve() or (path.exists() and path.stat().st_uid!=os.getuid()):
            raise ValueError("Unexpected installation path or owner")
    if not team.is_file():raise ValueError("Missing existing AI team")
    mode=team.stat().st_mode&0o777
    current=team.read_bytes()
    original=backup.read_bytes() if backup.exists() else current
    result=patched(original)
    if current not in (original,result):raise ValueError("Local team changes require review")
    source=Path(__file__).with_name(MODULE).read_bytes()
    previous=mod.read_bytes() if mod.exists() else None
    if previous is not None and previous!=source and hashlib.sha256(previous).hexdigest()!=PREVIEW:
        raise ValueError("Local module changes require review")
    if action=="check":return "active" if current==result and mod.exists() else "stock"
    if action=="rollback":
        if current!=original:replace(team,original,mode)
        # A team already running from an older snapshot may still import the helper.
        return "stock"
    storage.mkdir(mode=0o700,parents=True,exist_ok=True)
    if storage.stat().st_uid!=os.getuid() or storage.stat().st_mode&0o077:
        raise ValueError("Expected private backup directory")
    if not backup.exists():replace(backup,original,0o600)
    if previous!=source:replace(mod,source,0o700)
    if current!=result:replace(team,result,mode)
    return "active"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("check","activate","rollback"))
    print(setup(Path.home(),parser.parse_args().action))
