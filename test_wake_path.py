"""Verify the shipped watcher with an isolated user service and an empty private directory."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid


class NewProposalWake(unittest.TestCase):
    def test_atomic_proposals_wake_once_each_and_retained_files_do_not_retrigger(self):
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime or not (Path(runtime)/"bus").exists():
            self.skipTest("A systemd user manager is required")
        unit_root=Path(runtime)/"systemd/user"
        unit_root.mkdir(exist_ok=True,parents=True)
        name="field-review-test-"+uuid.uuid4().hex
        path_unit=unit_root/(name+".path")
        service_unit=unit_root/(name+".service")
        run=lambda *args:subprocess.run(["systemctl","--user",*args],capture_output=True,text=True,timeout=15,check=True)
        with tempfile.TemporaryDirectory(prefix="field-review-wake-") as temp:
            base=Path(temp)
            queue=base/"queue"
            events=base/"events"
            worker=base/"worker.py"
            worker.write_text("from pathlib import Path\np=Path(__file__).with_name('events')\nwith p.open('a') as f:f.write('wake\\n')\n")
            spec=(Path(__file__).parent/"orangepi-controller-review.path").read_text()
            path_unit.write_text(spec.replace("%h/.local/state/corvon-maintenance/proposals",str(queue)).replace("orangepi-ai-improvement.service",name+".service"))
            service_unit.write_text("[Service]\nType=oneshot\nExecStart=/usr/bin/python3 "+str(worker)+"\n")
            count=lambda:len(events.read_text().splitlines()) if events.exists() else 0
            def until(expected):
                deadline=time.monotonic()+4
                while time.monotonic()<deadline and count()<expected:time.sleep(.05)
                self.assertEqual(count(),expected)
            try:
                run("daemon-reload");run("start",path_unit.name)
                self.assertEqual(queue.stat().st_mode&0o777,0o700)
                self.assertEqual(count(),0)
                for i in (1,2):
                    # The producer prepares in the same filesystem and publishes by atomic rename.
                    draft=base/"draft"
                    draft.write_text("{}")
                    draft.replace(queue/(str(i)+".json"))
                    until(i)
                    time.sleep(.4)
                    self.assertEqual(count(),i)
            finally:
                subprocess.run(["systemctl","--user","stop",path_unit.name,service_unit.name],capture_output=True,timeout=15)
                path_unit.unlink(missing_ok=True);service_unit.unlink(missing_ok=True)
                run("daemon-reload")


if __name__=="__main__":unittest.main()
