import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('display_transport', Path(__file__).with_name('display_transport.py'))
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.authority = transport.TimeAuthority({'device_id': 'display_1', 'key': bytes(range(32))})
        self.request = {'device_id': 'display_1', 'nonce_hex64': 'ab' * 32}

    def test_canonical_signature_interoperability(self):
        with patch.object(self.authority, 'synchronized', return_value=True), patch.object(transport.time, 'time', return_value=1792771200):
            reply = self.authority.answer(self.request)
        canonical = b'flight-team-time-v1\ndisplay_1\n' + b'ab' * 32 + b'\n1792771200\n'
        self.assertEqual(transport.time_message('display_1', self.request['nonce_hex64'], 1792771200), canonical)
        self.assertEqual(reply['mac_hex64'], hmac.new(bytes(range(32)), canonical, hashlib.sha256).hexdigest())
        for field in ('device_id', 'nonce_hex64', 'unix'):
            changed = dict(reply)
            changed[field] = 'different' if field != 'unix' else changed[field] + 1
            forged = transport.time_message(changed['device_id'], changed['nonce_hex64'], changed['unix'])
            self.assertFalse(hmac.compare_digest(reply['mac_hex64'], hmac.new(bytes(range(32)), forged, hashlib.sha256).hexdigest()))

    def test_clock_fails_closed(self):
        with patch.object(self.authority, 'synchronized', return_value=False):
            self.assertIsNone(self.authority.answer(self.request))
        for epoch in (0, transport.LOWER_EPOCH - 1, transport.UPPER_EPOCH):
            with patch.object(self.authority, 'synchronized', return_value=True), patch.object(transport.time, 'time', return_value=epoch):
                self.assertIsNone(self.authority.answer(self.request))

    def test_malformed_or_other_device_rejected(self):
        for body in ([], None, {}, {'device_id': 'other', 'nonce_hex64': 'ab' * 32},
                     {'device_id': 'display_1', 'nonce_hex64': 'x' * 64},
                     {'device_id': 'display_1', 'nonce_hex64': 'ab' * 32, 'path': '/api/login'},
                     {'device_id': ['display_1'], 'nonce_hex64': 'ab' * 32}):
            with self.assertRaises(ValueError):
                self.authority.answer(body)

    def test_rate_budget_and_expiry(self):
        with patch.object(transport.time, 'monotonic', return_value=10):
            for _ in range(12):
                self.assertTrue(self.authority.permitted('10.42.0.10'))
            self.assertFalse(self.authority.permitted('10.42.0.10'))
        with patch.object(transport.time, 'monotonic', return_value=71):
            self.assertTrue(self.authority.permitted('10.42.0.10'))

    def test_synchronization_query_failure_is_closed(self):
        with patch.object(transport.subprocess, 'run', side_effect=OSError):
            self.assertFalse(self.authority.synchronized())

    def test_listener_filter_rejects_public_and_unapproved_addresses(self):
        for address, expected in (('10.42.0.1', {'10.42.0.1'}), ('192.168.1.10', set()), ('8.8.8.8', set())):
            with patch.object(transport, 'interface_ipv4', return_value=address) as command:
                self.assertEqual(transport.interface_addresses([transport.ipaddress.ip_network('10.42.0.0/24')]), expected)
            command.assert_called_once_with('ap0')

    def test_real_linux_ioctl_uses_allowed_inet_family(self):
        import sys
        if sys.platform != 'linux': self.skipTest('Linux ioctl integration')
        self.assertEqual(transport.interface_ipv4('lo'), '127.0.0.1')

    def test_unprovisioned_keeps_existing_api(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(transport.read_config(Path(root) / 'absent.json'))


if __name__ == '__main__':
    unittest.main()
