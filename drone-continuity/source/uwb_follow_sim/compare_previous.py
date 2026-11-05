"""Reproduce four missed cases in the saved PREVIOUS candidate, not a drone."""
import importlib.util
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parent.parent
out=root/"outputs/uwb-desk-verification-20261007"
spec=importlib.util.spec_from_file_location("previous_uwb_candidate",out/"before/uwb_follow.py")
old=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=old
spec.loader.exec_module(old)

def primed(distance=7):
    gate=old.FollowGate()
    for t in (0,.1,.2): gate.add_range(old.RangeSample(old.TAG_ADDRESS,old.IDENTITY_PAYLOAD,distance,t))
    return gate

def evaluate(gate,t=.25,bearing=0,pilot=False):
    return gate.evaluate(t,old.VisionSample(old.TAG_ADDRESS,bearing,.95,t),
        follow_enabled=True,pilot_override=pilot,navigation_healthy=True,flight_mode_allowed=True)

rows=[]
cases=(("nonfinite_range",evaluate(primed(float("nan")))),
       ("nonfinite_camera_bearing",evaluate(primed(),bearing=float("nan"))))
for name,cmd in cases:
    rows.append(dict(case=name,failure_reproduced=bool(cmd.forward_mps or cmd.yaw_rate_dps),
        old_request={"forward_mps":cmd.forward_mps,"yaw_rate_dps":cmd.yaw_rate_dps}))
gate=primed();evaluate(gate,pilot=True);cmd=evaluate(gate,.3)
rows.append(dict(case="automatic_follow_resume_after_pilot_takeover",failure_reproduced=bool(cmd.forward_mps)))
gate=primed()
for i in range(3,600): gate.add_range(old.RangeSample(old.TAG_ADDRESS,old.IDENTITY_PAYLOAD,7,i/10))
cmd=evaluate(gate,59.95)
rows.append(dict(case="frozen_controller_cached_identity_treated_as_live",failure_reproduced=bool(cmd.forward_mps)))
report={"scope":"previous simulation candidate only; no physical aircraft commands",
        "regressions":rows,"all_four_reproduced":all(x["failure_reproduced"] for x in rows)}
(out/"previous-regressions.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
print(json.dumps(report,indent=2))
raise SystemExit(0 if report["all_four_reproduced"] else 1)
