"""Compile both paths of the real sketch without uploading to any board."""
import json
from pathlib import Path
import shutil
import subprocess
import argparse

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cli",type=Path,required=True)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--build-root",type=Path,required=True)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    here=Path(__file__).resolve().parent
    target=args.build_root.resolve()/"operating-fixture"/"xiao_tag"
    target.mkdir(parents=True,exist_ok=True)
    # Public fixture only. It is never an installable release or private pairing.
    prefix='#define UWB_AES_KEY "0123456789ABCDEFFEDCBA9876543210"\n#define UWB_RESET_WIRED 1\n'
    (target/"xiao_tag.ino").write_text(prefix+(here/"xiao_tag/xiao_tag.ino").read_text(),encoding="utf-8")
    shutil.copyfile(here/"xiao_tag/RadioProtocol.h",target/"RadioProtocol.h")
    log=args.report.with_suffix(".log")
    command=[str(args.cli.resolve()),"compile","--fqbn","rp2040:rp2040:seeed_xiao_rp2350",
             "--config-file",str(args.config.resolve()),"--build-path",
             str(args.build_root.resolve()/"operating-build"),"--warnings","all",str(target)]
    run=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=300)
    log.write_text(run.stdout+run.stderr,encoding="utf-8")
    result={"board":"Seeed XIAO RP2350 ARM","core":"rp2040:rp2040@6.2.0",
            "operating_code_compile_passed":run.returncode==0,"log":str(log.resolve()),
            "no_hardware_upload":True,"public_fixture_not_for_flashing":True}
    args.report.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    raise SystemExit(run.returncode)

if __name__=="__main__": main()
