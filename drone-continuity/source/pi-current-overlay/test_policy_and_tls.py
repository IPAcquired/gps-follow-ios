import importlib.machinery
import importlib.util
import json
from pathlib import Path
import socket
import sys
import ssl
import tempfile
import threading
import time
import unittest
import subprocess
from unittest.mock import patch
import display_transport


def load(name, filename):
    loader = importlib.machinery.SourceFileLoader(name, str(Path(__file__).with_name(filename)))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


sys.path.append('/mnt/c/Users/Daddy Nate/Documents/Codex/2026-10-09/referenced-chatgpt-conversation-this-is-an/work')
companion = load('candidate_companion', 'orangepi-companion')
helper = load('candidate_helper', 'orangepi-wifi-control')


class PolicyTests(unittest.TestCase):
    def test_default_unavailable_policy_is_disabled(self):
        with tempfile.TemporaryDirectory() as root, patch.object(helper, 'STATE', Path(root)):
            self.assertFalse(helper.update_policy_status()['enabled'])

    def test_policy_selection_only_never_executes_maintenance(self):
        with tempfile.TemporaryDirectory() as root, patch.object(helper, 'STATE', Path(root)):
            for value in ('true', 1, [], None):
                with self.assertRaises(ValueError):
                    helper.dispatch({'action': 'update_policy', 'enabled': value})
            with patch.object(helper, 'flight_guard', side_effect=ValueError('flight active')):
                self.assertTrue(helper.dispatch({'action': 'update_policy', 'enabled': True})['enabled'])
                self.assertFalse(helper.dispatch({'action': 'update_policy', 'enabled': False})['enabled'])
            self.assertTrue((Path(root) / 'update-policy.json').exists())
            with patch.object(helper, 'flight_guard'):
                self.assertTrue(helper.dispatch({'action': 'update_policy', 'enabled': True})['enabled'])
                self.assertFalse(helper.dispatch({'action': 'update_policy', 'enabled': False})['enabled'])
            self.assertEqual(sorted(path.name for path in Path(root).iterdir()), ['update-policy.json'])

    def test_no_extra_paths_or_actions(self):
        with self.assertRaises(ValueError):
            helper.dispatch({'action': 'update_policy', 'enabled': True, 'path': '/etc/shadow'})

    def test_status_reports_backend_failure_honestly(self):
        with patch.object(companion, 'wifi_helper', side_effect=OSError), patch.object(companion, 'read_json', return_value={}):
            value = companion.update_status()
        self.assertFalse(value['security_updates_automatic'])
        self.assertEqual(value['auto_update_policy']['status'], 'unavailable')
        self.assertEqual(value['driver_updates'], 'inventory_and_review_only')

    def test_endpoint_requires_live_owned_session(self):
        request = object.__new__(companion.Handler)
        request.headers = {'Content-Type': 'application/json'}
        request.client_address = ('10.42.0.10', 12345)
        request.read_json = lambda maximum: {'enabled': True}
        request.session_token = lambda: 'own-test-token'
        replies = []
        request.send_json = lambda code, value: replies.append((int(code), value))
        with patch.dict(companion.SESSIONS, {}, clear=True), patch.object(companion, 'wifi_helper') as backend:
            request.update_policy_action()
            self.assertEqual(replies[-1][0], 401)
            backend.assert_not_called()
        with patch.dict(companion.SESSIONS, {'own-test-token': (time.monotonic() + 30, '10.42.0.10', 'unknown')}, clear=True), patch.object(companion, 'wifi_helper', return_value={'enabled': True}) as backend:
            request.update_policy_action()
            self.assertEqual(replies[-1][0], 200)
            backend.assert_called_once_with({'action': 'update_policy', 'enabled': True})


class TLSIntegration(unittest.TestCase):
    def test_verified_tls_and_pending_handshake_isolation(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        cert, key = folder / 'server.crt', folder / 'server.key'
        subprocess.run(['openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=orangepi-drone.local','-addext','subjectAltName=DNS:orangepi-drone.local','-keyout',str(key),'-out',str(cert)],check=True,capture_output=True)
        config = {'device_id': 'test', 'key': bytes(range(32)), 'networks': [], 'certificate': str(cert), 'private_key': str(key)}
        stop = threading.Event()
        sockets = []
        with patch.object(display_transport, 'read_config', return_value=config), patch.object(display_transport, 'interface_addresses', return_value={'127.0.0.1'}), patch.object(display_transport, 'serve_time_udp'):
            display_transport.start_display_transport(companion.CompanionServer, companion.Handler, stop)
            try:
                for _ in range(30):
                    try:
                        probe = socket.create_connection(('127.0.0.1', 8443), timeout=.2)
                        sockets.append(probe)
                        break
                    except OSError:
                        time.sleep(.1)
                # Two peers that send no TLS handshake must not block a valid client.
                sockets.append(socket.create_connection(('127.0.0.1', 8443), timeout=1))
                context = ssl.create_default_context(cafile=str(cert))
                with context.wrap_socket(socket.create_connection(('127.0.0.1', 8443), timeout=2), server_hostname='orangepi-drone.local') as client:
                    client.sendall(b'GET /api/identity HTTP/1.0\r\nHost: orangepi-drone.local\r\n\r\n')
                    response = b''
                    while True:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                    self.assertIn(b'200 OK', response)
                    self.assertIn(b'orange-pi-drone-companion-v1', response)
                for context, name in ((ssl.create_default_context(cafile=str(cert)), 'wrong.local'), (ssl.create_default_context(), 'orangepi-drone.local')):
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        with context.wrap_socket(socket.create_connection(('127.0.0.1', 8443), timeout=2), server_hostname=name):
                            pass
            finally:
                stop.set()
                for connection in sockets:
                    connection.close()
                time.sleep(.8)


if __name__ == '__main__':
    unittest.main()
