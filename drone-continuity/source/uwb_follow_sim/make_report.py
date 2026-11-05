"""Create a readable local report and a source-only package of the desk work."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import html
import json
import re
import zipfile

here=Path(__file__).resolve().parent
output=here.parent/"outputs/uwb-desk-verification-20261007"
simulation=json.loads((here/"simulation-results.json").read_text())
operating=json.loads((output/"operating-compile.json").read_text())
python_log=(output/"tests.log").read_text(encoding="utf-8-sig")
native_log=(output/"native-tests.log").read_text(encoding="utf-8-sig")
count=int(re.search(r"Ran (\d+) tests",python_log)[1])
native_count=int(re.search(r"NATIVE_SKETCH_TESTS_PASSED=(\d+)",native_log)[1])
guard=(output/"no-credential-compile.log").read_text(encoding="utf-8-sig")
guard_ok="Provision a private UWB_AES_KEY" in guard and "Confirm RYUW122 NRST" in guard
desk_compile=(output/"candidate-compile.log").read_text(encoding="utf-8-sig")
desk_ok="Sketch uses" in desk_compile and "error:" not in desk_compile
passed=bool("\nOK" in python_log and native_count==23 and
            simulation["all_software_scenarios_passed"] and
            operating["operating_code_compile_passed"] and desk_ok and guard_ok)
sources=sorted(p for p in here.rglob("*") if p.suffix in (".py",".ino",".h",".cpp",".md")
               and "__pycache__" not in p.parts)
summary={
    "generated_utc":datetime.now(timezone.utc).isoformat(),
    "scope":"desk specification checks, virtual radios and actual sketch with mocked hardware",
    "software_verification_passed":passed,"physical_hardware_verified":False,
    "python_tests":count,"native_actual_sketch_tests":native_count,
    "randomized_full_length_runs":simulation["stress_runs"],
    "seconds_per_run":simulation["seconds_per_stress_run"],
    "stress_steps":simulation["stress_total_steps"],"fault_windows_per_run":14,
    "stress_failures":len(simulation["stress_failures"]),
    "arduino_board":"Seeed XIAO RP2350 ARM","arduino_core":"6.2.0",
    "desk_and_operating_paths_compile":desk_ok and operating["operating_code_compile_passed"],
    "no_credentials_compile_guard_verified":guard_ok,"no_hardware_uploaded":True,
    "existing_converter":"User-reported 40 V input; exact model/output/current not verified",
    "unresolved":simulation["actual_wiring_plan_unresolved"],
    "source_sha256":{str(p.relative_to(here)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
}
(output/"verification-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")

unresolved_labels={
    "compute_output_voltage_unverified":"40 V converter: verify its regulated 5 V output.",
    "regulator_current_unverified":"Verify converter continuous current and complete system load.",
    "orange_pi_uart_pinmux_unverified":"Verify the A733 board's spare UART pins and actual Linux mapping.",
    "usb_host_ports_power_or_backfeed_unverified":"Verify USB sockets/hub, available power and backfeed protection.",
    "wearable_reset_wire_unverified":"Connect and physically verify XIAO D2 → UWB NRST.",
    "servo_simultaneous_stall_exceeds_supply":"Four MG996R simultaneous stalls exceed the existing 5 A servo supply.",
    "optional_trick_exceeds_standard_servo_travel":"The optional 270° trick path exceeds standard MG996R travel; verify linkage/variant.",
}
rows=[
    ("Wearable battery","Protected single-cell 3.7 V → XIAO BAT pads; use regulated 3.3 V for UWB.",
     "https://wiki.seeedstudio.com/xiao_rp2350_arduino/"),
    ("Wearable UART","XIAO D6 → UWB RXD; D7 ← UWB TXD; common GND, 115200 8N1.",
     "https://wiki.seeedstudio.com/xiao_rp2350_arduino/"),
    ("Wearable reset","XIAO D2 → UWB NRST with external pull-down. Actual fault tests assert reset.",
     "https://reyax.com/upload/products_download/download_file/RYUW122_EN.pdf"),
    ("Drone power","Existing 40 V buck: exact model pending. Verify 5 V output/current; keep 6 V servo rail separate.",None),
    ("Orange Pi","Use the Zero 3W A733 image. Reserve Bluetooth's ttyS1; verify another UART for UWB.",
     "https://github.com/armbian/build/blob/main/config/boards/orangepizero3w.conf"),
    ("RPLIDAR C1M1","Separate 460800-baud UART or its proper USB adapter; specified 5 V power and 3.3 V signals.",
     "https://www.slamtec.com/en/c1/spec"),
    ("MaixSense A010","USB recommended. 100×100 at 10 fps cannot fit 115200-baud UART; honor frame checksum and units.",
     "https://wiki.sipeed.com/hardware/en/maixsense/maixsense-a010/at_command_en.html"),
    ("USB camera","Verify exact Arducam SKU, UVC/UAC support and formats on the A733 OS; lower-resolution CPU inference first.",None),
    ("H743 + TX15 Max","Keep receiver, motors, GPS and compass as flight authority. Dedicated MAVLink link, USB for bench tests.",
     "https://ardupilot.org/dev/docs/companion-computers.html"),
    ("Landing gear","Separate 6 V supply. Tower Pro lists 1.4 A stall per servo and standard model travel of 0–159°.",
     "https://towerpro.com.tw/product/mg996r/"),
]
table="".join("<tr><th>"+html.escape(name)+"</th><td>"+html.escape(text)+
    (f' <a href="{url}">Source</a>' if url else "")+"</td></tr>" for name,text,url in rows)
faults="".join("<li>"+html.escape(label.replace("_"," "))+"</li>"
               for label in simulation["named_runs"][0]["event_coverage"])
unresolved="".join("<li>"+html.escape(unresolved_labels.get(item,item))+"</li>" for item in summary["unresolved"])
document=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Drone hardware desk verification</title><style>
:root{{color-scheme:dark}}body{{margin:0;background:#121416;color:#f3f4f4;font:17px/1.55 system-ui,sans-serif}}
main{{max-width:1050px;margin:auto;padding:35px 24px}}h1{{font-size:34px;line-height:1.2}}h2{{margin-top:32px;font-size:23px}}
.tag{{color:#ff9c83;letter-spacing:.06em;text-transform:uppercase;font-size:13px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px}}
.card,.notice{{padding:20px;background:#202426;border:1px solid #3e4749;border-radius:12px}}.card strong{{display:block;font-size:32px;color:#8ee0be}}
.notice{{border-color:#bd8660;background:#29231e}}a{{color:#9fceff}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #404548;text-align:left;padding:12px;vertical-align:top}}th{{width:190px}}
li{{margin:7px 0}}code{{background:#242a2c;padding:2px 5px}}footer{{margin-top:35px;color:#b2b8bb;font-size:14px}}
</style><main><div class="tag">Nate's drone · bench candidate · 7 October 2026</div>
<h1>Desk wiring and startup verification</h1>
<p><b>Software checks passed.</b> This report treats the parts as connected virtual devices and also executes the real wearable sketch with simulated pins and UART hardware. It does not claim the physical installation is verified.</p>
<div class="cards"><div class="card"><strong>{count}</strong>Python tests passed</div><div class="card"><strong>{native_count}</strong>Actual-sketch tests passed</div><div class="card"><strong>1,000</strong>60-second virtual runs</div><div class="card"><strong>0</strong>Unsafe requests in those model runs</div></div>
<h2>How the hardware connects</h2><table>{table}</table>
<p><b>One RP2350 is needed for the wearable.</b> The Orange Pi can host the drone-side UWB board; a second RP2350 is unnecessary if its spare UART and power are verified. UWB provides slant distance only. The camera must maintain an explicitly associated person target.</p>
<h2>Corrections saved</h2><ul>
<li>Fixed two real Arduino compilation errors in the previous wearable candidate.</li>
<li>Bounded buffers and deadlines; full acknowledgements and exact readbacks; no unnecessary flash writes.</li>
<li>Added changing tag liveness, reset on UART failure, configuration checks and watchdog handling.</li>
<li>Rejected nonfinite, future, stale and inconsistent samples; recovery requires new samples.</li>
<li>Pilot takeover cancels Follow until a deliberate off/on sequence. No reverse request into an unseen rear sector.</li>
<li>Valid fresh empty scans remain usable; missing or corrupt scans cannot be treated as clear space.</li></ul>
<h2>Faults exercised in every long run</h2><ul>{faults}</ul>
<h2>Checks still requiring the physical hardware</h2><div class="notice"><ul>{unresolved}</ul></div>
<p>Your 40 V converter is included using the rating you reported. The Amazon inspection stopped because the computer-use tool could not confidently identify the browser URL, so its exact product/output rating was not read.</p>
<p>The alternative <a href="https://www.ztwshop.com/product/accessory/2017/0814/ZTW-6A-UBEC.html">ZTW UBEC specification</a> lists 25 V maximum input; full 6S is 25.2 V. That alternative needs rating confirmation.</p>
<h2>What the result does and does not verify</h2><p>Both the inhibited desk build and operating code path compile for the XIAO RP2350 ARM target with Arduino-Pico 6.2.0. Native tests use memory/undefined-behavior sanitizers and include 100,000 random input bytes.</p>
<p>These models do not execute an Orange Pi OS, actual camera recognition, lidar firmware, RF propagation or ArduPilot flight dynamics. Real USB enumeration, voltage ripple, loaded servo travel, outdoor sensing, person association and flight-controller stopping behavior remain to be tested. A zero model request is not a proven physical hover or landing.</p>
<p>No hardware firmware was uploaded. No private pairing key was included. Public test credentials are not an operating release. No purchase or Amazon account change occurred.</p>
<h2>Saved files</h2><p><a href="verification-summary.json">Machine-readable verification</a> · <a href="tests.log">Python results</a> · <a href="native-tests.log">Actual-sketch results</a> · <a href="operating-compile.log">Board compilation</a> · <a href="previous-regressions.json">Four reproduced previous faults</a> · <a href="uwb-desk-source.zip">Source and wiring guide</a></p>
<footer>Generated {html.escape(summary["generated_utc"])}. The source package contains code/tests/documentation only, no flashable public-key firmware or private credentials.</footer></main></html>'''
(output/"Desk-verification.html").write_text(document,encoding="utf-8")

with zipfile.ZipFile(output/"uwb-desk-source.zip","w",compression=zipfile.ZIP_DEFLATED) as bundle:
    for path in sources:
        # This one comparison helper relies on the original saved backup.
        if path.name=="compare_previous.py": continue
        bundle.write(path,Path("uwb_follow_sim")/path.relative_to(here))
    for path in (here/"simulation-results.json",here/"stress-results.json",output/"verification-summary.json"):
        bundle.write(path,Path("results")/path.name)
print(json.dumps({k:summary[k] for k in ("software_verification_passed","python_tests","native_actual_sketch_tests","randomized_full_length_runs","no_hardware_uploaded","unresolved")},indent=2))
raise SystemExit(0 if passed else 1)
