"""Import an explicitly selected, read-only mounted flight-controller card as the desktop owner."""
import argparse
from pathlib import Path
import subprocess

from postflight_store import Deferred, Intake, mounted


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("logs",type=Path,help="Absolute path to the card's APM/LOGS directory")
    p.add_argument("--expected-fs-uuid",required=True,help="Expected UUID of the selected FC card")
    args=p.parse_args()
    result=subprocess.run(["findmnt","-n","-o","UUID","--target",str(args.logs)],
                          check=True,text=True,capture_output=True,timeout=5)
    if not result.stdout.strip() or result.stdout.strip().casefold()!=args.expected_fs_uuid.casefold():
        raise Deferred("unexpected_card_identity")
    print(mounted(Intake(Path.home()),args.logs,"mounted:"+result.stdout.strip().casefold()),"files checked")


if __name__=="__main__":main()
