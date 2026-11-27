"""Exercise the scoped systemd budget and abandoned-owner recovery on non-model test units."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


class ScopedBudget(unittest.TestCase):
    def test_new_service_kernel_budget_and_recovery_after_owner_exit(self):
        runtime=Path(os.environ.get("XDG_RUNTIME_DIR","/missing"))
        if not (runtime/"bus").exists():self.skipTest("A systemd user manager is required")
        run=lambda *a,**k:subprocess.run(a,capture_output=True,text=True,timeout=35,**k)
        key="review-fixture-"+uuid.uuid4().hex
        units=runtime/"systemd/user";units.mkdir(parents=True,exist_ok=True)
        srv=[key+"-"+k+".service" for k in ("quality","long","fast")]
        private=runtime/(key+"-state")
        with tempfile.TemporaryDirectory(prefix=key) as d:
            d=Path(d);source=Path(__file__).with_name("orangepi_review_budget.py").read_text()
            for old,new in zip(("orangepi-ai-quality.service","orangepi-ai-long.service","orangepi-ai.service"),srv):
                source=source.replace(old,new)
            source=source.replace('runtime/"orangepi-review-budget"',repr(str(private)))
            source=source.replace("folder="+repr(str(private)),"folder=Path("+repr(str(private))+")")
            (d/"orangepi_review_budget.py").write_text(source)
            fake=( "import fcntl,types\nfrom pathlib import Path\n"
                  +"PROFILES=[types.SimpleNamespace(service=n) for n in "+repr(srv[::-1])+"]\n"
                  +"def acquire_orchestration_lock():\n f=Path("+repr(str(d/"lock"))+").open('a+');fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);return f\n"
                  +"def wait_healthy(*a):pass\n")
            (d/"orangepi-ai-team").write_text(fake)
            runner=d/"run.py"
            runner.write_text("import os,sys,runpy,json\nfrom pathlib import Path\n"
                +"import orangepi_review_budget as b\nt=runpy.run_path(str(Path(__file__).with_name('orangepi-ai-team')))\n"
                +"with t['acquire_orchestration_lock'](),b.capped_services(t):\n"
                +" b.ctl('start',b.HEAVY[0]);pid=int(b.setting(b.HEAVY[0],'MainPID'))\n"
                +" p=Path('/proc')/str(pid);cg=Path('/sys/fs/cgroup')/(p/'cgroup').read_text().strip().split(':')[-1].lstrip('/')\n"
                +" assert (cg/'cpu.max').read_text().split()==['150000','100000']\n"
                +" assert b'AI_THREADS=2' in (p/'environ').read_bytes().split(b'\\0')\n"
                +" assert {b'LLAMA_ARG_BATCH=256',b'LLAMA_ARG_UBATCH=64'} <= set((p/'environ').read_bytes().split(b'\\0'))\n"
                +" if len(sys.argv)>1:os._exit(32)\n"
                +" b.ctl('stop',b.HEAVY[0])\n")
            try:
                for n in srv:
                    (units/n).write_text("[Service]\nEnvironment=AI_THREADS=8\nCPUAccounting=yes\nExecStart=/bin/sleep 100\n")
                run("systemctl","--user","daemon-reload",check=True)
                for abort in (False,True):
                    res=run(sys.executable,"-B",str(runner),*(["abort"] if abort else []))
                    self.assertEqual(res.returncode,32 if abort else 0,res.stderr)
                    end=time.monotonic()+12
                    while (private/"lease.json").exists() and time.monotonic()<end:time.sleep(.1)
                    self.assertFalse((private/"lease.json").exists())
                    for n in srv:
                        self.assertEqual(run("systemctl","--user","show",n,"-p","CPUQuotaPerSecUSec","--value").stdout.strip(),"infinity")
                        self.assertNotEqual(run("systemctl","--user","is-active",n).returncode,0)
            finally:
                run("systemctl","--user","stop",*srv)
                for n in srv:
                    (units/n).unlink(missing_ok=True)
                    child=units/(n+".d")
                    if child.is_dir():
                        for p in child.glob("zzzz-field-review-*.conf"):p.unlink()
                        child.rmdir()
                if private.is_dir():
                    for p in private.iterdir():
                        if p.is_file():p.unlink()
                    private.rmdir()
                run("systemctl","--user","daemon-reload")


if __name__=="__main__":unittest.main()
