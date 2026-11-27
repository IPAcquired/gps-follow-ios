import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screen_sockets import EXTRA, approve, approved_sockets


class ApprovedSocketTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.directory = Path(scratch.name)
        self.primary = self.directory/"direct-topology"
        self.primary.write_text("3-1")
        self.primary.chmod(0o600)
        self.extra = self.directory/EXTRA
        self.attached = ("/dev/ttyUSB0", "3-1.4", "19")

    def test_authenticated_new_socket_preserves_primary_and_works_again_after_replug(self):
        with patch("screen_sockets.port_location", return_value=self.attached), patch("screen_sockets.prove_screen") as proof:
            self.assertTrue(approve(self.primary, "/dev/ttyUSB0"))
            self.assertFalse(approve(self.primary, "/dev/ttyUSB0"))
            proof.assert_called_once_with("/dev/ttyUSB0", self.directory)
        self.assertEqual(self.primary.read_text(), "3-1")
        self.assertEqual(approved_sockets(self.primary), ("3-1", "3-1.4"))
        self.assertEqual(self.extra.stat().st_mode & 0o777, 0o600)

    def test_rejects_unpaired_and_device_swap(self):
        with patch("screen_sockets.port_location", return_value=self.attached), \
                patch("screen_sockets.prove_screen", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                approve(self.primary, "/dev/ttyUSB0")
        with patch("screen_sockets.prove_screen"), \
                patch("screen_sockets.port_location", side_effect=[self.attached, (*self.attached[:2], "20")]):
            with self.assertRaises(RuntimeError):
                approve(self.primary, "/dev/ttyUSB0")
        self.assertFalse(self.extra.exists())

    def test_untrusted_lists_preserve_primary_only(self):
        self.extra.write_text('["3-1.*"]')
        self.extra.chmod(0o600)
        self.assertEqual(approved_sockets(self.primary), ("3-1",))
        self.extra.write_text('["3-1.4"]')
        self.extra.chmod(0o644)
        self.assertEqual(approved_sockets(self.primary), ("3-1",))
        self.extra.unlink()
        self.extra.symlink_to(self.primary)
        self.assertEqual(approved_sockets(self.primary), ("3-1",))
        self.primary.chmod(0o644)
        self.assertEqual(approved_sockets(self.primary), ())


if __name__ == "__main__":
    unittest.main()
