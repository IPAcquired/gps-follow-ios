import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import install_model_review as installer


class OfflineInstallation(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.home=Path(temp.name)
        original=Path(os.environ.get("FIELD_AI_BIN",str(Path.home()/"bin")))
        if any(not (original/n).is_file() for n in installer.HASHES):
            self.skipTest("Verified baseline AI entry points unavailable")
        target=self.home/"bin";target.mkdir(mode=0o700)
        for n in installer.HASHES:
            shutil.copyfile(original/n,target/n);(target/n).chmod(0o755)
        self.target=target

    def files(self):return {n:installer.read(self.target/n) for n in installer.NAMES}

    def test_upgrade_rollback_recovery_and_modified_install(self):
        orig=self.files();state=installer.prepare(self.home)
        template=self.target/installer.NAMES[0]
        self.assertFalse(template.exists())
        installer.activate(self.home,True);proposed=self.files()
        self.assertNotEqual(orig,proposed)
        self.assertEqual(installer.prepare(self.home),state)
        installer.activate(self.home,True);installer.activate(self.home,False)
        self.assertEqual(orig,self.files())
        def fail_second(p,b,m):
            if p.name=="orangepi-ai-team":raise OSError("injected later write failure")
            installer.put(p,b,m)
        with self.assertRaises(OSError):installer.activate(self.home,True,write=fail_second)
        self.assertEqual(orig,self.files())
        installer.put(state/"transaction.json",b'{"forward":true}',0o600)
        installer.put(template,proposed[template.name],0o644)
        installer.activate(self.home,True);self.assertEqual(proposed,self.files())
        (self.target/"orangepi-ai-team").write_bytes(b"later owner edit")
        with self.assertRaises(RuntimeError):installer.activate(self.home,False)
        self.assertEqual((self.target/"orangepi-ai-team").read_bytes(),b"later owner edit")


if __name__=="__main__":unittest.main()
