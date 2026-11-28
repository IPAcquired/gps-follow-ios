"""Exercise update, recovery and enrollment guards against an in-memory flash device."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import screen_update as u


class Flash:
    def __init__(self):
        self.data = bytearray(b"\xff") * u.CAPACITY

    def read_flash(self, address, size):
        return bytes(self.data[address:address + size])

    def flash_md5sum(self, address, size):
        return hashlib.md5(self.read_flash(address, size)).hexdigest()

    def write(self, address, payload):
        self.data[address:address + len(payload)] = payload


class ScreenUpdateTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name)
        self.flash = Flash()
        self.old, self.new = b'\xe9' + b'p' * 100, b'\xe9' + b'q' * 260
        self.span = 4096
        self.table = struct.pack("<HBBII20x", 0x50aa, 0, 0, u.APP, u.APP_SIZE)
        self.table += struct.pack("<HBBII20x", 0x50aa, 0, 1, 0x1f0000, u.APP_SIZE)
        self.flash.write(0x8000, self.table)
        self.flash.write(u.APP, self.old)
        self.flash.write(u.APP + 512, b"prior sector tail")
        self.initial = bytes(self.flash.data)
        self.writes = []
        self.binding = bytes(range(6))
        self.reports = []
        self.patch("app_files", return_value=(self.old, self.new, self.table, self.span))
        self.patch("service", return_value=SimpleNamespace(returncode=0))
        self.patch("loader", side_effect=lambda *args: contextlib.nullcontext(self.flash))
        self.patch("verify_guard")
        self.patch("probe", side_effect=self.probe)
        self.port = ("tty1", "cookie")
        modules = {"direct_usb": SimpleNamespace(find_direct=lambda mac: self.port),
                   "esptool": SimpleNamespace(cmds=SimpleNamespace(write_flash=self.write))}
        shim = patch.dict(sys.modules, modules)
        shim.start()
        self.addCleanup(shim.stop)

    def patch(self, name, **kwargs):
        p = patch.object(u, name, **kwargs)
        value = p.start()
        self.addCleanup(p.stop)
        return value

    def write(self, stub, options):
        [(address, stream)] = options.addr_filename
        self.assertFalse(options.erase_all)
        self.assertEqual(address, u.APP)
        data = stream.read()
        self.writes.append(data)
        stub.write(address, b"\xff" * ((len(data) + 4095) // 4096 * 4096))
        stub.write(address, data)

    def probe(self, *args):
        if self.reports:
            return self.reports.pop(0)
        return 1

    def run_update(self, mode):
        with contextlib.redirect_stdout(None):
            u.transaction(mode, self.state, self.binding)

    def test_install_retry_restore_exact_private_backup(self):
        self.run_update("install")
        self.run_update("install")
        self.assertEqual(self.writes, [self.new])
        self.run_update("restore")
        self.run_update("restore")
        self.assertEqual(bytes(self.flash.data), self.initial)
        self.assertEqual(len(self.writes), 2)
        for path in self.state.iterdir():
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_postboot_failure_automatically_restores(self):
        self.reports = [1, None, 1]
        with self.assertRaisesRegex(RuntimeError, "Running application"):
            self.run_update("install")
        self.assertEqual(bytes(self.flash.data), self.initial)
        self.assertEqual(json.loads((self.state / "transaction.json").read_bytes())["phase"], "restored")

    def test_unknown_image_and_alternate_bootable_slot_refused(self):
        self.flash.write(0x1f0000, b'\xe9')
        with self.assertRaisesRegex(RuntimeError, "Alternate"):
            self.run_update("install")
        self.flash.write(0x1f0000, b'\xff')
        self.flash.write(u.APP, b'?')
        with self.assertRaisesRegex(RuntimeError, "Unrecognized"):
            self.run_update("install")
        self.assertEqual(self.writes, [])

    def test_interrupted_write_restore_does_not_need_bootable_app(self):
        self.run_update("install")
        path = self.state / "transaction.json"
        history = json.loads(path.read_bytes())
        history["phase"] = "writing"
        u.atomic_private(path, json.dumps(history).encode())
        self.flash.write(u.APP, b'?')
        with self.assertRaisesRegex(RuntimeError, "Finish interrupted"):
            self.run_update("install")
        self.run_update("restore")
        self.assertEqual(bytes(self.flash.data), self.initial)

    def test_backup_change_prevents_restore(self):
        self.run_update("install")
        path = self.state / "original-app-sectors.bin"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError, "digest differs"):
            self.run_update("restore")
        self.assertEqual(self.writes, [self.new])

    def test_disarm_guard_prevents_rom_access(self):
        u.verify_guard.side_effect = RuntimeError("stale")
        with self.assertRaisesRegex(RuntimeError, "stale"):
            self.run_update("install")
        u.loader.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_unresponsive_verified_install_restores_only_the_recorded_image(self):
        self.run_update("install")
        u.probe.side_effect = [u.StatusUnavailable(), 1]
        self.run_update("restore")
        self.assertEqual(bytes(self.flash.data), self.initial)

    def test_unresponsive_unknown_image_and_failed_calibration_refused(self):
        self.run_update("install")
        u.probe.side_effect = RuntimeError("Touch calibration is missing.")
        with self.assertRaisesRegex(RuntimeError, "Touch calibration"):
            self.run_update("restore")
        self.flash.write(u.APP, b"?")
        u.probe.side_effect = u.StatusUnavailable()
        with self.assertRaisesRegex(RuntimeError, "Offline display differs"):
            self.run_update("restore")
        self.assertEqual(self.writes, [self.new])

    def test_unresponsive_first_install_keeps_rom_closed(self):
        u.probe.side_effect = u.StatusUnavailable()
        with self.assertRaises(u.StatusUnavailable):
            self.run_update("install")
        u.loader.assert_not_called()


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.binding = bytes(range(6))
        self.now = [0.0]
        self.wire = SimpleNamespace(begin=self.begin, request=self.request)
        self.direct_timeout = type("TestDirectTimeout", (TimeoutError,), {})
        direct = SimpleNamespace(DirectTimeout=self.direct_timeout, open_direct=lambda *a: contextlib.nullcontext(self.wire))
        self.requests = []
        self.status = dict(display="Hosyond-E32R35T", screen_mac=self.binding.hex(), paired=True,
                           firmware="display-family", local_setup=True, staging_slice_version=2,
                           guard=False, desktop_live=False)
        self.details = [dict(display="Hosyond-E32R35T", firmware="display-family", local_setup=True,
                             wired_paired=True, touch_calibrated=True)]
        self.patches = [
            patch.dict(sys.modules, {"direct_usb": direct}),
            patch.object(u.time, "monotonic", side_effect=lambda: self.now[0]),
            patch.object(u.time, "sleep", side_effect=self.sleep),
            patch.object(u, "verify_guard"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def sleep(self, seconds):
        self.assertLessEqual(seconds, .2)
        self.now[0] += seconds

    def begin(self):
        self.assertGreaterEqual(self.now[0], 3.0)

    def request(self, action, deadline):
        self.requests.append(action)
        if action == "wired_status":
            return self.status
        self.assertEqual(action, "status")
        if len(self.details) > 1:
            item = self.details.pop(0)
        else:
            item = self.details[0]
        if isinstance(item, BaseException):
            self.now[0] = deadline
            raise item
        return item

    def test_rechecks_identity_after_detail_timeout_with_guarded_settling(self):
        self.details.insert(0, self.direct_timeout())
        self.assertIsNone(u.probe("tty", self.binding))
        self.assertEqual(self.requests, ["wired_status", "status"] * 2)
        self.assertGreater(u.verify_guard.call_count, 15)

    def test_missing_calibration_is_rejected(self):
        self.details[0]["touch_calibrated"] = False
        with self.assertRaisesRegex(RuntimeError, "calibration"):
            u.probe("tty", self.binding)

    def test_busy_screen_never_qualifies_as_unavailable(self):
        self.status["guard"] = True
        with self.assertRaisesRegex(RuntimeError, "did not become idle"):
            u.probe("tty", self.binding)
        self.assertNotIn("status", self.requests)

    def test_timeouts_are_bounded_and_identity_must_match(self):
        self.details = [self.direct_timeout()]
        with self.assertRaises(u.StatusUnavailable):
            u.probe("tty", self.binding)
        self.assertLess(self.now[0], 35)
        self.status["screen_mac"] = ""
        with self.assertRaisesRegex(RuntimeError, "Enrolled display"):
            u.probe("tty", self.binding)


if __name__ == "__main__":
    unittest.main()
