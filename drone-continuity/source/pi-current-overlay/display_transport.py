"""Optional display TLS and authenticated clock bootstrap; no flight authority."""
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import re
import ssl
import socket
import struct
import sys
import subprocess
import threading
import time

CONFIG = Path('/home/drone/.config/orangepi-companion/display-transport.json')
LOWER_EPOCH = 1792022400
UPPER_EPOCH = 4102444800
DEVICE_ID = re.compile(r'[A-Za-z0-9_-]{1,32}\Z')
HEX64 = re.compile(r'[0-9a-fA-F]{64}\Z')


def time_message(device_id, nonce, epoch):
    return f'flight-team-time-v1\n{device_id}\n{nonce}\n{epoch}\n'.encode('ascii')


def read_config(path=CONFIG):
    if not path.exists():
        return None
    if path.stat().st_mode & 0o077:
        raise ValueError('Display transport configuration must be owner-only')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Display transport configuration must be an object')
    if value.get('schema') != 1 or not DEVICE_ID.fullmatch(value.get('device_id', '')):
        raise ValueError('Invalid display transport identity')
    if not HEX64.fullmatch(value.get('key_hex', '')):
        raise ValueError('Invalid display pairing key')
    if not isinstance(value.get('allowed_networks'), list):
        raise ValueError('Display listeners require a network list')
    networks = [ipaddress.ip_network(item, strict=True) for item in value['allowed_networks']]
    if not networks or len(networks) > 4 or any(
        item.version != 4 or item.prefixlen < 24 or
        not any(item.subnet_of(private) for private in
                (ipaddress.ip_network('10.0.0.0/8'), ipaddress.ip_network('172.16.0.0/12'), ipaddress.ip_network('192.168.0.0/16')))
        for item in networks
    ):
        raise ValueError('Display listeners require explicit private /24 or narrower networks')
    for name in ('certificate', 'private_key'):
        if not isinstance(value.get(name), str) or not Path(value[name]).is_absolute():
            raise ValueError('Invalid TLS file location')
    if Path(value['private_key']).stat().st_mode & 0o077:
        raise ValueError('TLS private key must be owner-only')
    value['networks'] = networks
    value['key'] = bytes.fromhex(value.pop('key_hex'))
    return value


def interface_ipv4(interface):
    # AF_NETLINK is deliberately unavailable in the companion sandbox. Read the
    # configured interface address through an AF_INET ioctl instead.
    import fcntl
    encoded = interface.encode('ascii')
    if not 1 <= len(encoded) <= 15:
        raise ValueError('Invalid interface name')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        value = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack('256s', encoded))
    return socket.inet_ntoa(value[20:24])


def interface_addresses(networks):
    found = set()
    for interface in ('ap0',):
        try:
            ip = ipaddress.ip_address(interface_ipv4(interface))
        except OSError:
            continue
        if any(ip in network for network in networks):
            found.add(str(ip))
    return found


class TimeAuthority:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.requests = {}
        self.sync_checked = float('-inf')
        self.synced = False

    def synchronized(self):
        with self.lock:
            now = time.monotonic()
            if now - self.sync_checked >= 5:
                self.synced = False
                try:
                    result = subprocess.run(
                        ['/usr/bin/timedatectl', 'show', '--property=NTPSynchronized', '--value'],
                        capture_output=True, timeout=2, check=False)
                    self.synced = result.returncode == 0 and result.stdout.strip() == b'yes'
                except (OSError, subprocess.TimeoutExpired):
                    pass
                self.sync_checked = now
            return self.synced

    def permitted(self, address):
        with self.lock:
            now = time.monotonic()
            self.requests = {key: values for key, values in self.requests.items()
                             if values and now - values[-1] < 60}
            if address not in self.requests and len(self.requests) >= 128:
                return False
            values = [stamp for stamp in self.requests.get(address, []) if now - stamp < 60]
            if len(values) >= 12 or sum(len(items) for items in self.requests.values()) >= 48:
                return False
            values.append(now)
            self.requests[address] = values
            return True

    def answer(self, body):
        if not isinstance(body, dict) or set(body) != {'device_id', 'nonce_hex64'}:
            raise ValueError('Invalid clock request')
        device_id, nonce = body['device_id'], body['nonce_hex64']
        if not isinstance(device_id, str) or not isinstance(nonce, str):
            raise ValueError('Invalid clock request')
        if device_id != self.config['device_id'] or not HEX64.fullmatch(nonce):
            raise ValueError('Invalid clock request')
        # The paired Pi is the time authority; NTP synchronization is quality
        # evidence, not a claim that ordinary NTP is cryptographically secure.
        if not self.synchronized():
            return None
        epoch = int(time.time())
        if not LOWER_EPOCH <= epoch < UPPER_EPOCH:
            return None
        signature = hmac.new(self.config['key'], time_message(device_id, nonce, epoch), hashlib.sha256).hexdigest()
        return {'device_id': device_id, 'nonce_hex64': nonce, 'unix': epoch, 'mac_hex64': signature}


def serve_time_udp(authority, stop_event):
    # Only bootstrap uses a wildcard socket to receive broadcasts. Linux
    # IP_PKTINFO proves receipt on the private AP; source must be its subnet.
    try:
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_IP, 8, 1)  # Linux IP_PKTINFO
        udp.bind(('0.0.0.0', 8444))
        udp.settimeout(.5)
    except OSError:
        print('Display clock discovery unavailable', flush=True)
        return
    try:
        while not stop_event.is_set():
            try:
                raw, ancillary, flags, peer = udp.recvmsg(513, 128)
                if flags & socket.MSG_TRUNC or not 1 <= len(raw) <= 512:
                    continue
                received_index = None
                for level, kind, data in ancillary:
                    if level == socket.SOL_IP and kind == 8 and len(data) >= 12:
                        received_index, _, _ = struct.unpack('I4s4s', data[:12])
                try:
                    expected_index = socket.if_nametoindex('ap0')
                except OSError:
                    continue
                if received_index != expected_index or not ipaddress.ip_address(peer[0]) in ipaddress.ip_network('10.42.0.0/24'):
                    continue
                if not authority.permitted(peer[0]):
                    continue
                value = authority.answer(json.loads(raw))
                if value:
                    response = json.dumps(value, separators=(',', ':')).encode('ascii')
                    udp.sendto(response, peer)
            except (TimeoutError, socket.timeout):
                continue
            except (OSError, ValueError, TypeError, UnicodeError):
                continue
    finally:
        udp.close()


def start_display_transport(server_class, api_handler, stop_event, path=CONFIG):
    """Start optional listeners; missing provisioning never affects old HTTP API."""
    try:
        config = read_config(path)
        if config is None:
            return
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config['certificate'], config['private_key'])
    except (OSError, ValueError, KeyError, TypeError, ssl.SSLError):
        print('Display transport unavailable: verify private provisioning', flush=True)
        return

    class TLSCompanionServer(server_class):
        def handle_error(self, request, address):
            if isinstance(sys.exc_info()[1], (ssl.SSLError, TimeoutError, ConnectionError)):
                return
            super().handle_error(request, address)

        def get_request(self):
            client, address = super().get_request()
            try:
                client.settimeout(3)
                return context.wrap_socket(client, server_side=True, do_handshake_on_connect=False), address
            except BaseException:
                client.close()
                raise

    authority = TimeAuthority(config)
    threading.Thread(target=serve_time_udp, args=(authority, stop_event), name='display-clock', daemon=True).start()

    def manage():
        servers = {}
        try:
            while not stop_event.is_set():
                try:
                    wanted = interface_addresses(config['networks'])
                except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
                    wanted = set()
                for key in list(servers):
                    if key[0] not in wanted:
                        servers.pop(key).server_close()
                for address in sorted(wanted):
                    for port, cls, handler in ((8443, TLSCompanionServer, api_handler),):
                        key = (address, port)
                        if key not in servers:
                            try:
                                server = cls(key, handler)
                                server.timeout = .1
                                servers[key] = server
                            except OSError:
                                continue
                for server in list(servers.values()):
                    server.handle_request()
                stop_event.wait(.2 if servers else 2)
        finally:
            for server in servers.values():
                server.server_close()

    threading.Thread(target=manage, name='display-transport', daemon=True).start()
