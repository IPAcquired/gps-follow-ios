#!/usr/bin/python3
"""Read a bounded local DataFlash evidence summary as the signed-in owner."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time


DIGEST = re.compile(r"[0-9a-f]{64}")
GROUP = re.compile(r"APJ-1229/BT-10/BU-2/[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
SCOPE = "stable_controller_log_snapshot_may_span_arm_cycles"
LIMIT = 512 * 1024 * 1024


def bounded(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid count")
    return value


def private_info(path, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if path.resolve() != path or not kind(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("private owner file required")
    return info


def read(path, limit):
    private_info(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > limit):
            raise ValueError("invalid local evidence file")
        raw = stream.read(limit+1)
        if len(raw) != info.st_size:
            raise ValueError("evidence changed")
    return raw, info


def record(path, limit=512*1024):
    data, info = read(path, limit)
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("invalid local record")
    return value, info


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def file_age(now, stamp):
    age = now - stamp
    if not math.isfinite(age) or age < -5:
        raise ValueError("invalid local capture time")
    if age < 3600:
        return "under_one_hour"
    return "under_one_day" if age < 86400 else "historical"


def compact_latest(home, now):
    root = home / "flight-data"
    acq = root / "acquisition"
    for path in (root, acq, acq/"reports", acq/"snapshots", root/"profile"):
        private_info(path, directory=True)
    profile, _ = record(root/"profile/current.json", 8*1024*1024)
    group = profile.get("controller_group")
    if not isinstance(group, str) or not GROUP.fullmatch(group) or profile.get("schema") != 1:
        raise ValueError("active board group unavailable")
    out = {"status":"local_evidence","active_cohort_completed_files":bounded(profile["files"],10**7),
           "active_cohort_completed_messages":bounded(profile["messages"],10**13),
           "latest_snapshot":{"status":"unavailable"}}
    try:
        pointer, synchronized = record(acq/"latest-snapshot.json", 8192)
        active, _ = record(acq/"latest-analysis.json")
        dg = pointer["sha256"]
        if (not isinstance(dg,str) or not DIGEST.fullmatch(dg) or pointer.get("schema")!=1
                or pointer.get("classification")!="stable_snapshot" or pointer.get("queued") is not False):
            return out
        saved, _ = record(acq/"reports"/(dg+".json"))
        raw = private_info(acq/"snapshots"/(dg+".BIN"))
        if (saved!=active or saved.get("sha256")!=dg or saved.get("scope")!=SCOPE or saved.get("schema")!=1
                or saved.get("controller_group")!=group or bounded(pointer.get("bytes"),LIMIT,1)!=raw.st_size):
            return out
        messages = bounded(saved["messages"], 10**10, 1)
        types = saved["message_types"]
        if (not isinstance(types,dict) or not 1 <= len(types) <= 1024
                or sum(bounded(n,10**10,1) for n in types.values()) != messages):
            return out
        if any(row["digest"]==dg for row in completed_catalog(root)):
            out["latest_snapshot"]={"status":"already_in_completed_catalog","additional_observations":0}
            return out
        captured_age = file_age(now, raw.st_mtime)
        file_age(now, synchronized.st_mtime)
        latest = {"status":"provisional_observation_only","matches_active_board":True,
                  "messages":messages,"message_type_count":len(types),"bytes":raw.st_size,
                  "capture_age":captured_age,"last_synchronized_utc":utc(synchronized.st_mtime),
                  "included_in_completed_totals":False,"may_span_arm_cycles":True}
        duration = saved.get("duration_seconds")
        if type(duration) in (int,float) and math.isfinite(duration) and 0 <= duration <= 365*86400:
            latest["log_duration_seconds"] = round(duration,1)
        # No source text, arbitrary field names, digests, positions or raw events enter a model prompt.
        for key,name in (("BAT","battery_records"),("ATT","attitude_records"),("GPS","gps_records"),("ARM","arming_records")):
            latest[name] = types.get(key,0)
        out["latest_snapshot"] = latest
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        pass
    return out


def model_context(home=None, now=None):
    try:
        return compact_latest(Path.home() if home is None else home,time.time() if now is None else now)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        return {"status":"unavailable"}


def completed_catalog(root):
    data,_=read(root/"completed-log-index.jsonl",32*1024*1024)
    lines=data.splitlines(keepends=True)
    if len(lines)<2:
        raise ValueError("incomplete completed catalog")
    head,tail=json.loads(lines[0]),json.loads(lines[-1])
    if (head.get("kind")!="completed_log_catalog" or head.get("schema")!=1
            or tail.get("kind")!="completed_log_catalog_end" or tail.get("records")!=len(lines)-2
            or tail.get("records_sha256")!=hashlib.sha256(b"".join(lines[1:-1])).hexdigest()):
        raise ValueError("invalid completed catalog")
    result=[]
    for raw in lines[1:-1]:
        row=json.loads(raw)
        dg=row.get("sha256")
        if not isinstance(dg,str) or not DIGEST.fullmatch(dg):
            raise ValueError("invalid completed digest")
        result.append({"digest":dg,"collection":"completed","bytes":bounded(row["bytes"],2**63-1,1)})
    return result


def history(home):
    root = home/"flight-data"
    acq = root/"acquisition"
    for path in (root,acq, acq/"reports"):
        private_info(path,directory=True)
    entries = {}
    for path in (acq/"reports").glob("*.json"):
        dg=path.stem
        if not DIGEST.fullmatch(dg):
            continue
        item,_=record(path)
        if item.get("sha256")==dg and item.get("scope")==SCOPE:
            entries[dg]={"digest":dg,"collection":"snapshot","messages":bounded(item["messages"],10**10,1)}
    for row in completed_catalog(root):
        entries[row["digest"]]=row
    return list(entries.values())


def show(home,digest):
    if not isinstance(digest,str) or not DIGEST.fullmatch(digest):
        raise ValueError("Use a full digest from the private history")
    root=home/"flight-data"
    entries={row["digest"]:row for row in history(home)}
    if digest not in entries:raise ValueError("Digest absent from local catalog")
    row=entries[digest]
    if row["collection"]=="snapshot":
        path=root/"acquisition/reports"/(digest+".json")
        analysis,info=record(path)
    else:
        private_info(root/"reports",directory=True)
        for path in (root/"reports").glob("*/*/*-"+digest[:12]+"*/report.json"):
            saved,info=record(path,8*1024*1024)
            if saved.get("schema")==2 and saved.get("source",{}).get("sha256")==digest:
                analysis=saved["analysis"]
                break
        else:raise ValueError("Completed report unavailable")
    types=analysis["message_types"]
    if not isinstance(types,dict) or len(types)>1024:raise ValueError("Invalid decoded message types")
    out=dict(row,messages=bounded(analysis["messages"],10**10,1),message_type_count=len(types),
             report_saved_utc=utc(info.st_mtime))
    duration=analysis.get("duration_seconds")
    if type(duration) in (int,float) and math.isfinite(duration) and 0<=duration<=365*86400:
        out["log_duration_seconds"]=round(duration,1)
    return out


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view",choices=("latest","history","show"),nargs="?",default="latest")
    parser.add_argument("digest",nargs="?",help="Full private digest for show")
    args=parser.parse_args()
    if (args.view=="show") != (args.digest is not None):parser.error("show requires one digest")
    if args.view=="show":result=show(Path.home(),args.digest)
    elif args.view=="history":result=history(Path.home())
    else:result=model_context()
    print(json.dumps(result,indent=2,sort_keys=True))
