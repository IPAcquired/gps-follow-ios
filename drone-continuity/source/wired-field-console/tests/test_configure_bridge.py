"""The commissioning CLI binds only the exact bridge the owner selects."""
import tempfile
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure_pi
from bridge_usb import Bridge


class CommissioningTests(unittest.TestCase):
    def test_production_exact_screen_version(self):
        self.assertEqual(configure_pi.VERSION,"flight-team-display-1.3.34-wired-paired-r3.3")

    def test_ambiguous_instance_and_changed_port_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/"ttyACM0";a.touch()
            b=Path(directory)/"ttyACM1";b.touch()
            expected=Bridge(str(a),"3-1","3-1/3:8","a"*64)
            other=Bridge(str(b),"3-2","3-2/3:9","b"*64)
            with patch("configure_pi.enumerate_bridges",return_value=[expected,other]):
                self.assertEqual(configure_pi.chosen_bridge(a),expected)
            with patch("configure_pi.enumerate_bridges",return_value=[other]):
                with self.assertRaises(ValueError):configure_pi.chosen_bridge(a)
            with patch("configure_pi.enumerate_bridges",return_value=[expected,other._replace(digest=expected.digest)]):
                with self.assertRaises(ValueError):configure_pi.chosen_bridge(a)

    @unittest.skipUnless(sys.platform=="linux","numerical UID and Unix filesystem socket required")
    def test_bad_broker_mode_and_symlink_declined_before_serial(self):
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_UNIX) as peer:
            root=Path(directory);local=root/"broker.sock";link=root/"fake.sock"
            peer.bind(str(local));local.chmod(0o644);link.symlink_to(local)
            args=["configure_pi.py","--screen-port","synthetic"]
            for node in (local,link):
                if node==link:local.chmod(0o600)
                with patch("configure_pi.owner_broker_path",return_value=node), \
                     patch("configure_pi.topology",return_value="1-2"),patch.object(sys,"argv",args), \
                     self.assertRaises(PermissionError):
                    configure_pi.main()

if __name__=="__main__":unittest.main()
