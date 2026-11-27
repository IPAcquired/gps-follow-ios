"""Exercise the actual shell monitor against a stateful RandR fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def fixture():
    file = Path(os.environ["DISPLAY_TEST_STATE"])
    s = json.loads(file.read_text())
    cmd = Path(sys.argv[0]).name
    args = sys.argv[1:]
    rc = 0
    if cmd == "xrandr" and args == ["--query"]:
        for name, connected, active in (("DP-1", s["dp"], s["da"]), ("HDMI-1", True, s["ha"])):
            print(name, "connected" if connected else "disconnected",
                  "1920x1080+0+0" if active else "", "(normal left inverted right x axis y axis)")
            if connected and (name == "HDMI-1" or s["modes"]):
                print("   ", "1280x720" if s["scenario"] == "720-only" else "1920x1080",
                      "60.00*" if active else "60.00")
        s["events"].append(["query", s["da"], s["ha"]])
    elif cmd == "xrandr":
        assert args[0] == "--output"
        s["events"].append(args)
        if args[1] == "HDMI-1":
            s["ha"] = "--off" not in args
        elif "--off" in args:
            s["da"] = False
        else:
            s["attempts"] += 1
            if s["scenario"] == "all-modesets-fail" or (
                s["scenario"] == "transient-fail" and s["polls"] < 1
            ):
                rc = 1
            elif s["modes"] and s["scenario"] != "modeset-no-crtc":
                s["da"] = True
        if not s["ha"] and not s["da"]:
            s["blackouts"] += 1
    elif cmd == "sleep" and args == ["2"]:
        s["polls"] += 1
        if s["polls"] == 1 and s["scenario"] == "late-edid":
            s["modes"] = True
        if s["polls"] == 1 and s["scenario"] == "dp-unplug":
            s["dp"] = False
            s["da"] = False
        if s["polls"] == 1 and s["scenario"] == "crtc-dropped":
            s["da"] = False
        if s["polls"] >= 3:
            file.write_text(json.dumps(s))
            # The monitor exits on a failing sleep. Use a sentinel to bound
            # this fixture without signalling processes or touching the display.
            sys.exit(23)
    file.write_text(json.dumps(s))
    sys.exit(rc)


def run(program, scenario):
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for name in ("xrandr", "sleep", "logger"):
            script = d / name
            script.write_text("#!/usr/bin/python3\n" + Path(__file__).read_text())
            script.chmod(0o755)
        state = d / "state"
        state.write_text(json.dumps(dict(scenario=scenario, dp=True, da=False, ha=True,
            polls=0, attempts=0, blackouts=0, modes=scenario not in ("missing-edid", "late-edid"), events=[])))
        env = {"DISPLAY_TEST_STATE": str(state), "PATH": str(d) + ":" + os.defpath, "LC_ALL": "C",
               "ORANGEPI_DISPLAY_POLICY": "dual" if scenario in ("dual", "crtc-dropped") else "prefer-dp"}
        result = subprocess.run(["/bin/sh", program], env=env, capture_output=True, timeout=20)
        return json.loads(state.read_text()), result.returncode


if __name__ == "__main__":
    if Path(sys.argv[0]).name in ("xrandr", "sleep", "logger"):
        fixture()
    else:
        directory = Path(__file__).resolve().parent
        scenarios = ("missing-edid", "late-edid", "all-modesets-fail", "modeset-no-crtc",
                     "transient-fail", "720-only", "dual", "dp-unplug", "crtc-dropped")
        for scenario in scenarios:
            s, rc = run(directory / "orangepi-display-monitor", scenario)
            assert rc == 23 and not s["blackouts"], (scenario, rc, s)
            if scenario in ("missing-edid", "all-modesets-fail", "modeset-no-crtc", "dp-unplug"):
                assert s["ha"] and not s["da"], (scenario, s)
            else:
                assert s["da"] and s["ha"] == (scenario in ("dual", "crtc-dropped")), (scenario, s)
            if scenario == "missing-edid":
                assert s["attempts"] == 0
            if scenario == "720-only":
                assert not any("--mode" in event for event in s["events"])
            for i, event in enumerate(s["events"]):
                if event == ["--output", "HDMI-1", "--off"]:
                    assert s["events"][i - 1][0:2] == ["query", True]
            print("PASS", scenario)
        print("Display scenarios passed:", len(scenarios))
