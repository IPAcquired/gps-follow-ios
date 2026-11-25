"""GPS-only local HTTPS listener. No desktop, files, flight or update routes."""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from display_transport import interface_ipv4

CONFIG = Path('/home/drone/.config/orangepi-companion/phone-browser/config.json')
ASSETS = Path('/home/drone/companion-phone')
PRIVATE = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))


class PhoneAccess:
    def __init__(self, config, store):
        self.config, self.store = config, store
        self.lock = threading.Lock()
        self.epoch = secrets.token_hex(16)
        self.last = 0.0
        self.sequence = 0
        self.source = None

    def authorized(self, value):
        if not isinstance(value, str) or not re.fullmatch(r'Bearer [0-9a-f]{64}', value):
            return False
        return time.time() < self.config['expires_unix'] and hmac.compare_digest(
            hashlib.sha256(value[7:].encode()).hexdigest(), self.config['token_sha256'])

    def accept(self, value, peer):
        if not isinstance(value, dict):
            raise ValueError('Expected object')
        with self.lock:
            now = time.monotonic()
            if now-self.last < .15:
                raise ValueError('Too many updates')
            if self.source is not None and peer != self.source and now-self.last < 10:
                raise ValueError('Another phone is sharing')
            expected = {'stop'} if value.get('stop') is True else {'lat','lon','accuracy_m','age_ms'}
            if set(value) != expected:
                raise ValueError('Invalid location fields')
            current = self.store.snapshot()
            if current['status'] == 'fresh' and current['provenance'] != 'authenticated_phone_browser':
                raise ValueError('Companion GPS is currently active')
            # A former browser session must not reuse an epoch retired when a
            # native Companion session took over. Rotate only after it expires.
            with self.store.lock:
                if self.epoch in self.store.retired:
                    self.epoch = secrets.token_hex(16)
            self.sequence += 1
            payload = dict(value,source='phone_gps',source_epoch=self.epoch,seq=self.sequence)
            result = self.store.accept(payload, provenance='authenticated_phone_browser')
            self.source, self.last = peer, now
            return result


def handler_for(access, assets=ASSETS):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        server_version = 'AXL-GPS'
        sys_version = ''

        def log_message(self, *_):
            pass  # No positions, capability URLs, or request headers in logs.

        def reply(self, code, data, kind='application/json'):
            if isinstance(data, dict):
                data = json.dumps(data, allow_nan=False, separators=(',', ':')).encode()
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(data)))
            if kind == 'application/x-apple-aspen-config':
                self.send_header('Content-Disposition','attachment; filename="AXL-Phone-GPS.mobileconfig"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Permissions-Policy', 'geolocation=(self), camera=(), microphone=()')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            host = self.headers.get('Host', '')
            return host in {'example-pi.local:8445', '192.168.1.176:8445'}

        def do_GET(self):
            if not self.valid_host():
                return self.reply(400, {'error':'Invalid host'})
            files = {'/':('index.html','text/html; charset=utf-8'),
                     '/AXL-Phone-GPS.mobileconfig':('AXL-Phone-GPS.mobileconfig','application/x-apple-aspen-config'),
                     '/phone.js':('phone.js','text/javascript; charset=utf-8'),
                     '/phone.css':('phone.css','text/css; charset=utf-8')}
            item = files.get(self.path)
            if not item:
                return self.reply(404, {'error':'GPS endpoint only'})
            return self.reply(200, (assets/item[0]).read_bytes(), item[1])

        def do_POST(self):
            if not self.valid_host() or self.headers.get('Origin') != 'https://'+self.headers.get('Host',''):
                return self.reply(403, {'error':'Same-origin HTTPS required'})
            if self.path != '/location':
                return self.reply(404, {'error':'GPS endpoint only'})
            if not access.authorized(self.headers.get('Authorization')):
                return self.reply(401, {'error':'Scan the current private GPS link on your computer'})
            if self.headers.get('Content-Type') != 'application/json' or self.headers.get('Transfer-Encoding'):
                return self.reply(400, {'error':'JSON required'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 1 <= length <= 512:
                    raise ValueError('Invalid body size')
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('Incomplete body')
                value = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid number')))
                result = access.accept(value, self.client_address[0])
            except (ValueError, TypeError, OverflowError):
                return self.reply(422, {'error':'Location must be fresh, accurate within 30 m, and in range'})
            self.reply(200, {'accepted':True,'status':result['status'],'authority':'advisory_only','mavlink_transmit':False})
    return Handler


def start_phone_browser(store, stop_event, config_path=CONFIG):
    if not config_path.is_file():
        return
    try:
        if config_path.stat().st_mode & 0o077:
            raise ValueError('Private configuration required')
        config = json.loads(config_path.read_text())
        assert re.fullmatch('[0-9a-f]{64}', config['token_sha256'])
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(config['certificate'], config['private_key'])
        access = PhoneAccess(config, store)
    except (OSError, ValueError, KeyError, AssertionError, ssl.SSLError):
        print('Phone GPS HTTPS provisioning unavailable', flush=True)
        return
    serve_private_https(context, handler_for(access), stop_event, 8445)


def serve_private_https(context, handler, stop_event, port):
    """Bind only explicit local Wi-Fi addresses, with bounded TLS workers."""
    slots = threading.BoundedSemaphore(4)

    class Server(ThreadingHTTPServer):
        use_tls = True
        daemon_threads = True
        allow_reuse_address = True
        request_queue_size = 4

        def get_request(self):
            client, address = super().get_request()
            try:
                client.settimeout(3)
                if not any(ipaddress.ip_address(address[0]) in n for n in PRIVATE):
                    raise OSError('Private network only')
                if self.use_tls:
                    return context.wrap_socket(client, server_side=True, do_handshake_on_connect=False), address
                return client, address
            except BaseException:
                client.close()
                raise

        def process_request(self, client, address):
            if not slots.acquire(False):
                self.shutdown_request(client)
                return
            try:
                super().process_request(client, address)
            except BaseException:
                slots.release()
                raise

        def process_request_thread(self, client, address):
            try:
                super().process_request_thread(client, address)
            finally:
                slots.release()

        def handle_error(self, *_):
            pass

    def manage():
        servers = {}
        try:
            while not stop_event.is_set():
                addresses = set()
                for interface in ('wlan0', 'ap0'):
                    try:
                        address = interface_ipv4(interface)
                        if any(ipaddress.ip_address(address) in n for n in PRIVATE):
                            addresses.add(address)
                    except (OSError, ValueError):
                        pass
                for address in set(servers)-addresses:
                    servers.pop(address).server_close()
                for address in addresses-set(servers):
                    try:
                        server = Server((address,port),handler)
                        server.timeout = .1
                        servers[address] = server
                    except OSError:
                        pass
                for server in servers.values():
                    server.handle_request()
                if not servers:
                    stop_event.wait(2)
        finally:
            for server in servers.values():
                server.server_close()
    threading.Thread(target=manage, name='private-https-'+str(port), daemon=True).start()
