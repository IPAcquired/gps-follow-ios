"""Run firmware and protocol tests on a Linux host, without opening any device."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--arduinojson",type=Path,default=root/"screen/.pio/libdeps/flight_team/ArduinoJson/src")
parser.add_argument("--staged-companion",type=Path,
                    help="Optional directory containing the CORVON overlay applied to the full companion release.")
args=parser.parse_args();screen=root/"screen";xiao=root/"xiao";tests=screen/"tests"
def run(cmd,cwd=None):
 subprocess.run([str(x) for x in cmd],cwd=cwd,check=True)
run([sys.executable,"-B","-m","unittest","discover","-q","-p","test_*.py"],root/"pi")
run([sys.executable,"-B",root/"tests/test_profile_standalone.py"])
if args.staged_companion:
 run([sys.executable,"-B","test_controller_profile.py"],args.staged_companion.resolve())
run([sys.executable,"-B",root/"tests/test_configure.py"])
run([sys.executable,"-B",xiao/"verify_pio.py"])
run([sys.executable,"-B",xiao/"verify_cdc.py"])
run([sys.executable,"-B",tests/"field_log_test.py"])
run([sys.executable,"-B",tests/"test_storage_check.py"])
with tempfile.TemporaryDirectory(prefix="wired-tests-") as scratch:
 out=Path(scratch)
 if not (args.arduinojson/"ArduinoJson.h").is_file():raise SystemExit("Pass --arduinojson with ArduinoJson 6.21.5's src directory.")
 sources=(screen/"include/PersonalizationUI.h").read_text();start=sources.index("void renderXiaoLights(")
 (out/"xiao-ui.inc").write_text(sources[start:sources.index("\n}\n",start)+2])
 for n in ("verify_packets","verify_lights"):
  run(["g++","-std=c++17","-I",xiao,xiao/(n+".cpp"),"-o",out/n]);run([out/n])
 for n in ("test_backgrounds","test_wireless_edit","test_local_profile","test_profile","test_telemetry_filter","test_lights","test_lights_ui","test_notices"):
  run(["g++","-std=c++17","-I",tests,"-I",screen/"include","-I",out,"-I",args.arduinojson,tests/(n+".cpp"),"-o",out/n]);run([out/n])
 hal=out/"hal";hal.mkdir()
 for n in ("Arduino.h","WiFi.h","esp_wifi.h","NimBLEDevice.h"):(hal/n).write_text("#pragma once\n")
 run(["g++","-std=c++17","-I",hal,"-I",screen/"include","-I",args.arduinojson,tests/"wireless_driver_fixture.cpp","-o",out/"wireless"]);run([out/"wireless"])
 inflate=screen/"lib/WiredInflate/src";objs=[]
 for src in sorted(inflate.glob("*.c")):
  obj=out/(src.stem+".o");run(["gcc","-O2","-fPIC","-DUZLIB_CONF_PARANOID_CHECKS=1","-I",inflate,"-c",src,"-o",obj]);objs.append(obj)
 lib=out/"screen.so"
 run(["g++","-std=c++17","-fPIC","-shared","-O2","-DUZLIB_CONF_PARANOID_CHECKS=1","-I",tests,"-I",screen/"include","-I",inflate,tests/"auto_host.cpp",screen/"src/PairChannel.cpp",*objs,"-lmbedcrypto","-ljpeg","-o",lib])
 run([sys.executable,"-B",tests/"r3_test.py",lib])
print("Host tests passed.")
