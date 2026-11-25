"""Offline transaction tests. No ports, services, or real flash are opened."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import corvon_firmware as fw


HERE = Path(__file__).resolve().parent
PACKAGE, APP = fw.load_package(HERE)
EMPTY = b"\xff" * fw.FLASH


class Model:
    def __init__(self):
        self.device = "1" * 64
        self.flash = EMPTY
        self.storage = b"x" * 32768
        self.files = {}
        self.writes = []
        self.armed = False
        self.healthy = True
        self.kill_rename_ack = False
        self.cut_upload = False
        self.corrupt = False
        self.profile = {n: 0 for n in fw.SETTINGS}

    def settings(self):
        return self.profile.copy()

    def guard(self, expected):
        fw.require(not self.armed and self.device == expected, "ground guard")

    def health(self):
        fw.require(self.healthy, "barometer unhealthy")

    def root(self):
        return {n: len(v) for n, v in self.files.items()}

    def read(self, n, count, offset=0):
        if n == "@SYS/flash.bin": return self.flash[offset:offset+count]
        if n == "@SYS/storage.bin": return self.storage[offset:offset+count]
        return self.files[n[1:]][offset:offset+count]

    def upload(self, n, data):
        self.writes.append(("upload", n))
        self.files[n] = data[:1024] if self.cut_upload else data
        if self.corrupt:
            self.files[n] = b"!" + self.files[n][1:]
        if self.cut_upload:
            raise TimeoutError("interrupted transfer")

    def promote(self, n):
        self.writes.append(("rename", n))
        self.files[fw.TRIGGER] = self.files.pop(n)
        if self.kill_rename_ack:
            raise TimeoutError("ack lost after rename")

    def remove(self, n):
        self.writes.append(("remove", n))
        del self.files[n]

    def boot(self):
        self.files[fw.COMPLETE] = self.files.pop(fw.TRIGGER)
        self.flash = self.flash[:fw.BASE] + APP + b"\xff"*(fw.END-fw.BASE-len(APP)) + self.flash[fw.END:]


class TestUpdates(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.folder = Path(self.root.name)/"transaction"
        self.board = Model()
        mock = patch.object(fw, "BOOT_HASH", fw.sha(EMPTY[:fw.BASE]))
        mock.start(); self.addCleanup(mock.stop)

    def go(self, action, approval=None, now=100):
        return fw.transaction(self.board, action, HERE, self.folder, approval, now)

    def plan(self):
        proposal = self.go("prepare")
        self.assertEqual(self.board.writes, [])
        self.assertEqual((self.folder/"flash-before.bin").stat().st_size, fw.FLASH)
        self.assertEqual((self.folder/"parameters-before.bin").read_bytes(), self.board.storage)
        return proposal["approval_sha256"]

    def test_normal_update(self):
        token = self.plan()
        self.assertEqual(self.go("apply", token)["status"], "awaiting-cold-power-cycle")
        self.assertEqual(self.board.flash, EMPTY)
        with self.assertRaises(fw.FirmwareError): self.go("verify")
        self.board.boot()
        self.assertEqual(self.go("verify")["status"],"verified")
        self.assertIn(fw.COMPLETE,self.board.files)
        with self.assertRaises(fw.FirmwareError): self.go("cleanup","bad")
        self.assertTrue(self.go("cleanup", token)["marker_removed"])
        self.assertEqual(self.board.files, {})

    def test_noop(self):
        self.board.flash = self.board.flash[:fw.BASE]+APP+self.board.flash[fw.BASE+len(APP):]
        self.assertEqual(self.go("prepare")["status"],"already-current")
        self.assertFalse(self.folder.exists()); self.assertFalse(self.board.writes)

    def test_wrong_or_expired_approval(self):
        token=self.plan()
        for digest, now in [(None,110), ("bad",110),(token,1001)]:
            with self.assertRaises(fw.FirmwareError): self.go("apply",digest,now)
        self.assertFalse(self.board.writes)

    def test_stale_state_or_backup(self):
        token=self.plan()
        self.board.armed=True
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.board.armed=False
        self.board.profile["FRAME_CLASS"]=8
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.board.profile["FRAME_CLASS"]=0
        self.board.storage=b"z"*32768
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.board.storage=b"x"*32768
        (self.folder/"flash-before.bin").write_bytes(b"damaged")
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.assertFalse(self.board.writes)

    def test_board_or_bootloader_change(self):
        token=self.plan()
        self.board.device="2"*64
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.board.device="1"*64
        self.board.flash=b"!" + self.board.flash[1:]
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.assertFalse(self.board.writes)

    def test_existing_boot_markers_and_inert_collision(self):
        for name in fw.RESERVED:
            self.board.files={name:b"unrelated"}
            with self.assertRaises(fw.FirmwareError): self.go("prepare")
        self.board.files={}
        token=self.plan()
        inert=json.loads((self.folder/"proposal.json").read_bytes())["inert_name"]
        self.board.files[inert]=b"stranger"
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.assertFalse(self.board.writes)

    def test_interruption_before_rename(self):
        token=self.plan()
        self.board.cut_upload=True
        with self.assertRaises(TimeoutError): self.go("apply",token)
        self.assertNotIn(fw.TRIGGER,self.board.files)
        self.board.cut_upload=False
        self.go("apply",token)
        self.assertIn(fw.TRIGGER,self.board.files)

    def test_corrupt_inert_is_not_deleted(self):
        token=self.plan()
        self.board.corrupt=True
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.assertEqual(len(self.board.writes),1)
        self.assertNotIn(fw.TRIGGER,self.board.files)

    def test_ambiguous_rename_ack(self):
        token=self.plan()
        self.board.kill_rename_ack=True
        with self.assertRaises(TimeoutError): self.go("apply",token)
        with self.assertRaises(fw.FirmwareError): self.go("apply",token)
        self.board.boot()
        self.assertEqual(self.go("verify")["status"],"verified")

    def test_postflight_rejects_bad_sensor_image_or_marker(self):
        token=self.plan(); self.go("apply",token); self.board.boot()
        self.board.healthy=False
        with self.assertRaises(fw.FirmwareError): self.go("cleanup",token)
        self.board.healthy=True
        ok=self.board.flash
        self.board.flash=EMPTY
        with self.assertRaises(fw.FirmwareError): self.go("verify")
        self.board.flash=ok
        self.board.files[fw.COMPLETE]=b"foreign"
        with self.assertRaises(fw.FirmwareError): self.go("cleanup",token)
        self.assertEqual(self.board.files[fw.COMPLETE],b"foreign")

    def test_candidate_pin(self):
        path=Path(self.root.name)/fw.FILENAME
        path.write_bytes(b"!" + PACKAGE[1:])
        with self.assertRaises(fw.FirmwareError): fw.load_package(path.parent)


if __name__ == "__main__":
    unittest.main()
