"""Long event simulations of virtual endpoints; no physical devices opened."""
import json
import math
import random
from pathlib import Path
from desk_model import RadioEmulator, DeskRadioHost, DeskPlan, audit
from uwb_follow import FollowGate, VisionSample, LineFramer, parse_anchor_line, TAG_ADDRESS

TEST_KEY = "0123456789ABCDEFFEDCBA9876543210"  # Public test fixture only.
EVENTS = {
    "obstacle_in_path": (10,11), "rf_body_blockage": (15,16),
    "rf_channel_mismatch": (20,21), "camera_unplugged": (25,26),
    "wrong_person": (26,27), "delayed_camera_processing": (28,29),
    "unsupported_flight_mode": (31,32), "navigation_loss": (35,36),
    "second_rf_dropout": (40,41), "wearable_reboot": (42,43),
    "companion_brownout_or_fc_usb_loss": (45,46), "pilot_takeover": (50,51),
    "follow_off_after_takeover": (51,52), "wearable_mcu_frozen_radio_alive": (55,57),
}

def run(seed=743, seconds=60.0, dt=.1):
    rng=random.Random(seed)
    tag=RadioEmulator();anchor=RadioEmulator()
    tag_host=DeskRadioHost(tag,fragment_size=rng.randrange(1,20))
    anchor_host=DeskRadioHost(anchor,fragment_size=rng.randrange(1,20))
    tag_host.start(TEST_KEY,tag=True);anchor_host.start(TEST_KEY,tag=False)
    gate=FollowGate();counter=0
    counts={};coverage={k:0 for k in EVENTS};unsafe=[]
    maximum={"forward_mps":0.0,"yaw_rate_dps":0.0}
    last_new_uwb=None
    for i in range(round(seconds/dt)):
        t=round(i*dt,6)
        active={name for name,(start,end) in EVENTS.items() if start <= t < end}
        for name in active: coverage[name]+=1
        if t == 42:
            tag.reset();counter=0;tag_host.start(TEST_KEY,tag=True)
        if "wearable_mcu_frozen_radio_alive" not in active:
            counter=(counter+1)&0xFFFFFFFF
            tag_host.heartbeat(counter)
        tag.rf_open=not ({"rf_body_blockage","second_rf_dropout"}&active)
        tag.settings["CHANNEL"]="9" if "rf_channel_mismatch" in active else "5"
        true_distance=7+.8*math.sin(t/3)
        measured=true_distance+rng.gauss(0,.1)
        if i in (120,300,480): measured+=20  # Outliers, not presumed real obstacles.
        raw=anchor.range_response(tag,cm=round(measured*100))
        framer=LineFramer()
        # Exercise wire framing with random chunk boundaries.
        cursor=0
        while cursor < len(raw):
            size=rng.randrange(1,16)
            for line in framer.feed(raw[cursor:cursor+size]):
                sample=parse_anchor_line(line,t)
                if gate.add_range(sample,t): last_new_uwb=t
            cursor+=size
        vision=None if "camera_unplugged" in active else VisionSample(
            "OTHER001" if "wrong_person" in active else TAG_ADDRESS,
            15*math.sin(t),.92,t-1 if "delayed_camera_processing" in active else t)
        pilot="pilot_takeover" in active
        # A rebooted wearable does not silently resume; explicit OFF then re-enable.
        enabled=not ({"wearable_reboot","follow_off_after_takeover"}&active)
        nav="navigation_loss" not in active
        mode="unsupported_flight_mode" not in active
        link="companion_brownout_or_fc_usb_loss" not in active
        clear="obstacle_in_path" not in active
        cmd=gate.evaluate(t,vision,follow_enabled=enabled,pilot_override=pilot,
            navigation_healthy=nav,flight_mode_allowed=mode,armed=True,
            controller_link_healthy=link,obstacle_data_fresh=True,path_clear=clear,
            target_binding_confirmed=True)
        counts[cmd.state]=counts.get(cmd.state,0)+1
        maximum["forward_mps"]=max(maximum["forward_mps"],abs(cmd.forward_mps))
        maximum["yaw_rate_dps"]=max(maximum["yaw_rate_dps"],abs(cmd.yaw_rate_dps))
        stale=last_new_uwb is None or t-last_new_uwb >= .5-1e-9
        bad_camera=vision is None or vision.target_id != TAG_ADDRESS or t-vision.received_s >= .3-1e-9
        blocked=stale or bad_camera or pilot or not all((enabled,nav,mode,link,clear))
        bounded=0 <= cmd.forward_mps <= 1.5 and abs(cmd.yaw_rate_dps) <= 25
        if not bounded or blocked and (cmd.forward_mps or cmd.yaw_rate_dps):
            unsafe.append({"t":t,"state":cmd.state,"reason":cmd.reason})
    exercised=all(coverage.values()) if seconds >= 60 else False
    return dict(seed=seed,seconds=seconds,steps=round(seconds/dt),states=counts,
        event_coverage=coverage,all_events_exercised=exercised,
        maximum_request=maximum,unsafe_requests=unsafe,
        passed=not unsafe and exercised and counts.get("follow",0)>0)

if __name__=="__main__":
    directory=Path(__file__).parent
    samples=[run(seed) for seed in (743,122,2350,15,2026)]
    stress=[run(seed) for seed in range(1000)]  # Full 60 seconds, not the old 20-second run.
    report={"model":"virtual radio endpoints plus request gate; not physical flight",
            "named_runs":samples,"stress_runs":len(stress),"seconds_per_stress_run":60,
            "stress_total_steps":sum(x["steps"] for x in stress),
            "stress_failures":[x for x in stress if not x["passed"]],
            "actual_wiring_plan_unresolved":audit(DeskPlan()),
            "all_software_scenarios_passed":all(x["passed"] for x in samples+stress)}
    (directory/"simulation-results.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (directory/"stress-results.json").write_text(json.dumps({k:report[k] for k in
        ("stress_runs","seconds_per_stress_run","stress_total_steps","stress_failures","all_software_scenarios_passed")},indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "named_runs"},indent=2))
    raise SystemExit(0 if report["all_software_scenarios_passed"] else 1)
