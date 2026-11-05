"""Local TLS owner capability, limited to staging an iPhone hotspot profile."""
import hashlib
import hmac
import json
import re
import socket
import ssl
import threading
import time
import secrets
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from phone_browser import serve_private_https
from dashboard_transport import read_snapshot
from quick_connect import PairingCodes, start_pairing_bridge
from browser_desktop import exchange as desktop_exchange

CONFIG = Path('/home/drone/.config/orangepi-companion/field-setup.json')
ASSETS = Path('/home/drone/companion-field')


def helper(value):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(20)
        client.connect('/run/orangepi-field-wifi.sock')
        client.sendall(json.dumps(value, separators=(',', ':')).encode()+b'\n')
        data = b''
        while b'\n' not in data and len(data) < 4096:
            chunk = client.recv(4096-len(data))
            if not chunk:
                break
            data += chunk
        return json.loads(data)


def handler_for(config, assets=ASSETS, dispatch=helper, snapshot=read_snapshot, codes=None, desktop=desktop_exchange):
    lock = threading.Lock()
    last_save = [float('-inf')]
    sessions = {}
    reviewed = {}

    def join_epoch(ip):
        if not re.fullmatch(r'10\.42\.0\.(10|11|12)',ip):return 'upstream'
        try:return Path('/run/orangepi-field-joins',ip).read_text()[:64]
        except OSError:return 'local'

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        disable_nagle_algorithm = True
        server_version = 'AXL-Field'
        sys_version = ''

        def log_message(self, *_):
            pass

        def reply(self, code, value, kind='application/json', extra=None):
            data = json.dumps(value, allow_nan=False).encode() if isinstance(value, dict) else value
            self.send_response(code)
            if code>=400 or self.command=='GET':
                self.close_connection=True
                self.send_header('Connection','close')
            for key, item in {
                'Content-Type': kind, 'Content-Length': str(len(data)),
                'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                'X-Content-Type-Options': 'nosniff',
                'Permissions-Policy': 'geolocation=(), camera=(), microphone=()',
                'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; img-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            }.items():
                self.send_header(key, item)
            for key,item in (extra or {}).items():self.send_header(key,item)
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):
            return (len(self.headers.get_all('Host', [])) == 1 and
                    self.headers.get('Host') in {'orangepi-drone.local:8446', '192.168.1.176:8446'})

        def do_GET(self):
            if not self.host_ok():
                return self.reply(400, {'error': 'Invalid host'})
            path=urlsplit(self.path).path
            if path=='/captive-portal':
                ip=self.client_address[0]
                captive=ip.startswith('10.42.0.') and ip!='10.42.0.2' and reviewed.get(ip)!=join_epoch(ip)
                return self.reply(200,{'captive':captive,'user-portal-url':'https://orangepi-drone.local:8446/?setup=1'},'application/captive+json')
            item = {'/': ('index.html', 'text/html; charset=utf-8'),
                    '/field.js': ('field.js', 'text/javascript; charset=utf-8'),
                    '/desktop.js': ('desktop.js', 'text/javascript; charset=utf-8'),
                    '/field.css': ('field.css', 'text/css; charset=utf-8'),
                    '/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),
                    '/sw.js':('sw.js','text/javascript; charset=utf-8'),
                    '/icon.svg':('icon.svg','image/svg+xml'),
                    '/AXL-Field-Guide.pdf':('AXL-Field-Guide.pdf','application/pdf')}.get(path)
            if not item:
                return self.reply(404, {'error': 'No such route'})
            self.reply(200, (assets/item[0]).read_bytes(), item[1])

        def authorized(self, bearer_only=False):
            if time.time()>=config['expires_unix']:return False
            token=self.headers.get('Authorization','')
            if len(self.headers.get_all('Authorization',[]))==1 and re.fullmatch(r'Bearer [0-9a-f]{64}',token):
                return hmac.compare_digest(hashlib.sha256(token[7:].encode()).hexdigest(),config['token_sha256'])
            if bearer_only:return False
            try:
                cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                raw=cookies['__Host-axl_field'].value
                if not re.fullmatch('[0-9a-f]{64}',raw):return False
                return sessions.get(hashlib.sha256(raw.encode()).hexdigest(),0)>time.time()
            except (KeyError,ValueError):return False

        def do_POST(self):
            if (not self.host_ok() or len(self.headers.get_all('Origin', [])) != 1 or
                    self.headers.get('Origin') != 'https://'+self.headers.get('Host', '')):
                return self.reply(403, {'error': 'Same-origin HTTPS required'})
            if self.path not in ('/status','/hotspot','/session','/logout','/networks','/connect','/telemetry','/review','/pair','/desktop/unlock','/desktop/lock','/desktop/frame','/desktop/input'):
                return self.reply(404, {'error': 'Wi-Fi setup only'})
            if self.path != '/pair' and not self.authorized(bearer_only=self.path=='/session'):
                return self.reply(401, {'error': 'Open your private field setup link'})
            if (self.headers.get('Content-Type') != 'application/json' or
                    self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1):
                return self.reply(400, {'error': 'One bounded JSON body required'})
            try:
                size = int(self.headers['Content-Length'])
                if not 1 <= size <= (2048 if self.path=='/desktop/input' else 512):
                    raise ValueError()
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError()
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError()
                expected = {'/hotspot':{'ssid','password'},'/connect':{'ssid'},'/pair':{'code'},'/desktop/unlock':{'confirm'},'/desktop/frame':{'base'},'/desktop/input':{'event_id','command'}}.get(self.path,set())
                if set(value) != expected:
                    raise ValueError()
                if self.path.startswith('/desktop/'):
                    cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                    raw=cookies['__Host-axl_field'].value if '__Host-axl_field' in cookies else ''
                    if not re.fullmatch('[0-9a-f]{64}',raw) or sessions.get(hashlib.sha256(raw.encode()).hexdigest(),0)<=time.time():
                        return self.reply(401,{'error':'Unlock this browser with its private QR first'})
                    action=self.path.rsplit('/',1)[1]
                    if action=='unlock' and value['confirm'] is not True:raise ValueError()
                    if action=='frame' and (not isinstance(value['base'],str) or not re.fullmatch('(?:[0-9a-f]{64})?',value['base'])):raise ValueError()
                    owner=hashlib.sha256(('browser-owner:'+raw+':'+self.client_address[0]).encode()).hexdigest()
                    result=desktop(dict(value,owner=owner,action=action))
                    return self.reply(200 if result.get('ok') else 409,result)
                # A slow network query must never hold the session lock or stall telemetry.
                if self.path=='/telemetry':return self.reply(200,{'ok':True,'snapshot':snapshot()})
                if self.path in ('/status','/networks'):
                    result=dispatch({'action':self.path[1:]})
                    if self.path=='/status':result['review_required']=reviewed.get(self.client_address[0])!=join_epoch(self.client_address[0])
                    return self.reply(200 if result.get('ok') else 422,result)
                with lock:
                    if self.path in ('/session','/pair'):
                        now=time.time()
                        for key in list(sessions):
                            if sessions[key]<=now:del sessions[key]
                        if len(sessions)>=16:return self.reply(429,{'error':'Too many paired browser sessions; log out an old session'})
                        if self.path=='/pair' and (codes is None or not codes.consume(value['code'])):
                            return self.reply(401,{'error':'QR expired or already used. Tap NEW QR on the display.'})
                        key=secrets.token_hex(32);seconds=int(min(7*86400,config['expires_unix']-now))
                        sessions[hashlib.sha256(key.encode()).hexdigest()]=now+seconds
                        return self.reply(200,{'ok':True},extra={'Set-Cookie':f'__Host-axl_field={key}; Path=/; Max-Age={seconds}; Secure; HttpOnly; SameSite=Strict'})
                    if self.path=='/logout':
                        cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''))
                        if '__Host-axl_field' in cookies:sessions.pop(hashlib.sha256(cookies['__Host-axl_field'].value.encode()).hexdigest(),None)
                        return self.reply(200,{'ok':True},extra={'Set-Cookie':'__Host-axl_field=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Strict'})
                    if self.path=='/review':
                        reviewed[self.client_address[0]]=join_epoch(self.client_address[0])
                        return self.reply(200,{'ok':True,'network_changed':False})
                    if self.path == '/hotspot':
                        now = time.monotonic()
                        if now-last_save[0] < 5:
                            return self.reply(429, {'error': 'Wait five seconds before saving again'})
                        last_save[0] = now
                    action={'/status':'status','/hotspot':'save_hotspot','/networks':'networks','/connect':'request_connect'}[self.path]
                    result = dispatch(dict(value, action=action))
                    if self.path=='/status':
                        result['review_required']=reviewed.get(self.client_address[0])!=join_epoch(self.client_address[0])
                self.reply(200 if result.get('ok') else 422, result)
            except (ValueError, TypeError, OverflowError):
                self.reply(422, {'error': 'Invalid desktop request' if self.path.startswith('/desktop/') else 'Check the network name and password; no other settings are accepted'})
            except OSError:
                self.reply(503, {'error': 'Pi service unavailable; reconnect and try again'})
    return Handler


if __name__ == '__main__':
    if CONFIG.stat().st_mode & 0o077:
        raise SystemExit('Private configuration required')
    config = json.loads(CONFIG.read_text())
    if not re.fullmatch('[0-9a-f]{64}', config['token_sha256']):
        raise SystemExit('Invalid configuration')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(config['certificate'], config['private_key'])
    stop = threading.Event()
    codes=PairingCodes(config['expires_unix'])
    start_pairing_bridge(codes, stop)
    serve_private_https(context, handler_for(config, codes=codes), stop, 8446)
    stop.wait()
