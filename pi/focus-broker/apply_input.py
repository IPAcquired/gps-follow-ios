"""Apply the four reviewed arrows and the owner-environment helper to a staged Companion copy."""
import argparse
from pathlib import Path
import re

parser=argparse.ArgumentParser()
parser.add_argument("source",type=Path)
parser.add_argument("output",type=Path)
args=parser.parse_args()
if args.output.exists():raise SystemExit("Choose an unused output path.")
old=args.source.read_text(encoding="utf8")
anchor='        "arrowleft": "Left", "arrowright": "Right", "arrowup": "Up", "arrowdown": "Down",'
line='        "left": "Left", "right": "Right", "up": "Up", "down": "Down",'
if old.count(anchor)!=1:raise SystemExit("This Companion version uses a different native keyboard implementation.")
if line not in old:old=old.replace(anchor,anchor+"\n"+line)
replacement="        from browser_desktop import owner_x11_environment\n        environment = owner_x11_environment()"
if replacement not in old:
    expr=r'        environment = os\.environ\.copy\(\)\n        environment\.update\(\{"DISPLAY": ":[0-9]+", "XAUTHORITY": "[^"\r\n]+"\}\)'
    old,matches=re.subn(expr,replacement,old)
    if matches!=1:raise SystemExit("Native X11 setup differed; retain the owner's source for review.")
args.output.write_text(old,encoding="utf8",newline="\n")
