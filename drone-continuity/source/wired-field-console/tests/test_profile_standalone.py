"""Exercise the public hardware reference and route qualification without a controller."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi/controller-profile"))
import controller_profile


class ProfileTests(unittest.TestCase):
    def test_offline_reference_and_ports(self):
        reference = controller_profile.board_reference()
        self.assertEqual(reference["source_status"], "verified_offline_copy")
        self.assertFalse(reference["live_firmware_bytes_attested"])
        self.assertEqual(reference["configured_board_id"], 1229)
        links = controller_profile.SENSOR_LINKS
        self.assertEqual([links[name]["pi_port"] for name in
                          ("flight_controller", "rplidar", "matrix_lidar", "camera")],
                         ["UART0", "UART2", "UART7", "USB"])

    def test_fresh_source_and_silent_or_unapproved_route(self):
        identity = {"system_id": 16, "component_id": 1}
        sample = dict(connected=True, last_heartbeat_unix=98.5, h743_source=identity,
                      expected_source=identity, transport="/dev/ttyS0")
        with patch.object(controller_profile, "verified_route", side_effect=lambda x: x == "/dev/ttyS0"):
            for changes, state, presence in (
                ({}, "matching", "heartbeat"),
                (dict(transport="/dev/rfcomm0"), "mismatch", "heartbeat"),
                (dict(transport="/dev/ttyUSB0"), "unverified", "heartbeat"),
                (dict(expected_source={"system_id": 17, "component_id": 1}), "mismatch", "heartbeat"),
                (dict(expected_source={"system_id": True, "component_id": 1}), "unverified", "heartbeat"),
                (dict(last_heartbeat_unix=97), "unverified", "unknown"),
                (dict(last_heartbeat_unix=101), "unverified", "unknown"),
                (dict(connected=False), "unverified", "unknown"),
            ):
                with self.subTest(changes=changes):
                    result = controller_profile.controller_profile({**sample, **changes}, 100)
                    self.assertEqual((result["source_state"], result["presence"]), (state, presence))


if __name__ == "__main__":
    unittest.main()
