import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import install_budget as b


class Installer(unittest.TestCase):
    def test_versioned_install_rollback_and_failed_write(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);folder=home/"bin";folder.mkdir()
            module=folder/b.MODULE
            fixture=b"def review(team):\n"+b.ORIGINAL+b"        return True\n"
            module.write_bytes(fixture);module.chmod(0o644);digest=hashlib.sha256(fixture).hexdigest()
            run=lambda forward,writer=b.put:b.install(home,forward,digest,writer)
            def fail(p,data):
                if p==module:raise RuntimeError("injected write error")
                b.put(p,data)
            with self.assertRaises(RuntimeError):run(True,fail)
            self.assertEqual(module.read_bytes(),fixture);self.assertFalse((folder/b.HELPER).exists())
            run(True);run(True)
            self.assertIn(b.BOUND,module.read_bytes());self.assertTrue((folder/b.HELPER).exists())
            self.assertEqual(stat.S_IMODE(module.stat().st_mode),0o644)
            run(False);run(False)
            self.assertEqual(module.read_bytes(),fixture);self.assertFalse((folder/b.HELPER).exists())
            self.assertEqual(stat.S_IMODE(module.stat().st_mode),0o644)
            module.write_bytes(b"owner edit")
            with self.assertRaises(RuntimeError):run(True)
            self.assertEqual(module.read_bytes(),b"owner edit")


if __name__=="__main__":unittest.main()
