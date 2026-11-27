"""Decode one privately retained snapshot with the existing read-only DataFlash parser."""
import json
import os
from pathlib import Path
import re
import runpy
import sys

from postflight_store import Deferred, file_hash, private, publish_json


def summarize(home, digest, analyzer):
    if not re.fullmatch("[a-f0-9]{64}",digest):raise Deferred("invalid_snapshot_digest")
    root=private(home/"flight-data/acquisition")
    reports=private(root/"reports")
    source=private(root/"snapshots")/(digest+".BIN")
    if not source.is_file() or source.is_symlink() or file_hash(source)!=digest:
        raise Deferred("snapshot_integrity_error")
    path=reports/(digest+".json")
    if path.exists():
        report=json.loads(path.read_bytes())
        if report.get("sha256")!=digest:raise Deferred("invalid_prior_summary")
    else:
        sys.path.insert(0,str(analyzer.parent))
        try:
            api=runpy.run_path(str(analyzer))
            data=api["analyze"](source)
            types=data["message_types"]
            useful=sum(v for k,v in types.items() if k not in {"FMT","FMTU","BAD_DATA"})
            if useful<=0:raise Deferred("snapshot_has_no_data_records")
            report={"schema":1,"sha256":digest,"scope":"stable_controller_log_snapshot_may_span_arm_cycles",
                    "controller_group":api["log_controller_group"](data),"messages":data["messages"],
                    "duration_seconds":data["duration_seconds"],"message_types":types,
                    "observations":data["efficiency_and_control_observations"]}
        finally:
            sys.path.pop(0)
        publish_json(path,report)
    publish_json(root/"latest-analysis.json",report)
    return report


if __name__=="__main__":
    os.nice(12)
    summarize(Path.home(),sys.argv[1],Path(__file__).resolve().parent/"analyzer/orangepi-bin-analyzer")
