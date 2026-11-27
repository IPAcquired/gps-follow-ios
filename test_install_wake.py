import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
import install_wake as installer


class WakeInstall(unittest.TestCase):
    def test_install_readback_rollback_and_failure(self):
        with tempfile.TemporaryDirectory() as name:
            home=Path(name);bin_dir=home/"bin";bin_dir.mkdir()
            base=b"fixture"
            (bin_dir/"orangepi_model_review.py").write_bytes(base)
            expected=hashlib.sha256(base).hexdigest()
            target=home/".config/systemd/user"/installer.UNIT
            s=dict(active=False,enabled=False,fail=False)
            def ctl(*args,check=True):
                a=args[0];text="";code=0
                if a=="show":text="loaded"
                elif a=="enable":
                    s.update(active=True,enabled=True)
                    if s["fail"]:raise RuntimeError("injected start failure")
                elif a=="disable":s.update(enabled=False,active=s["active"] and "--now" not in args)
                elif a=="stop":s["active"]=False
                elif a=="is-active":text="active" if s["active"] else "inactive";code=0 if s["active"] else 3
                elif a=="is-enabled":text="enabled" if s["enabled"] else "disabled";code=0 if s["enabled"] else 1
                return subprocess.CompletedProcess(args,code,stdout=text)
            def run(action):
                installer.deploy(home,action,ctl,expected)
            run("install");run("install")
            self.assertTrue(s["active"]);self.assertTrue(s["enabled"])
            self.assertEqual(target.read_bytes(),installer.SOURCE.read_bytes())
            run("rollback");run("rollback")
            self.assertFalse(target.exists());self.assertFalse(s["active"]);self.assertFalse(s["enabled"])
            home.chmod(0o700);target.parent.chmod(0o775)
            run("install");run("rollback")
            home.chmod(0o755)
            with self.assertRaises(RuntimeError):run("install")
            home.chmod(0o700)
            s["fail"]=True
            with self.assertRaises(RuntimeError):run("install")
            self.assertFalse(target.exists());self.assertFalse(s["active"]);self.assertFalse(s["enabled"])
            target.write_bytes(b"locally managed")
            with self.assertRaises(RuntimeError):run("rollback")
            with self.assertRaises(RuntimeError):run("install")
            self.assertEqual(target.read_bytes(),b"locally managed")


if __name__=="__main__":unittest.main()
