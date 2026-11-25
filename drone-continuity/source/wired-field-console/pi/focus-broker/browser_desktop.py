"""Owner-leased desktop on a same-UID Unix bridge; no public desktop listener."""
import base64,hashlib,hmac,json,os,re,secrets,socket,stat,struct,subprocess,threading,time
from pathlib import Path
PATH=Path('/run/user')/str(os.getuid())/'axl-display-bridge/desktop.sock'
MAX_REPLY=2*1024*1024
_focus_key=secrets.token_bytes(32)

def owner_x11_environment():
    display=os.environ.get("DISPLAY") or ":0"
    if not re.fullmatch(r":[0-9]+(?:\.[0-9]+)?",display):raise PermissionError("Local X11 display required")
    authority=Path(os.environ.get("XAUTHORITY") or (Path.home()/".Xauthority")).resolve(strict=True)
    info=authority.stat()
    if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode) or info.st_mode&0o022:
        raise PermissionError("Owner X11 authority unavailable")
    return dict(os.environ,DISPLAY=display,XAUTHORITY=str(authority))

def focus_snapshot():
    """Return an opaque change marker. Query only window IDs and accessibility state."""
    import desktop_focus
    metadata=desktop_focus.snapshot()
    unknown={"focus_known":False,"focus_editable":False,"focus_revision":None}
    try:
        env=owner_x11_environment()
        result=subprocess.run(["/usr/bin/xdotool","getwindowfocus","-f"],env=env,capture_output=True,text=True,timeout=.35)
        if result.returncode:return unknown
        active=subprocess.run(["/usr/bin/xdotool","getactivewindow"],env=env,capture_output=True,text=True,timeout=.35)
    except (OSError,subprocess.SubprocessError):return unknown
    ids=result.stdout.split()+([] if active.returncode else active.stdout.split())
    if not 1<=len(ids)<=2 or any(not s.isdecimal() or len(s)>20 or int(s)<=1 for s in ids):
        return unknown
    # A bare X server may have a focused client without a window-manager active-window property.
    stamp=json.dumps([ids,metadata.get("revision"),bool(metadata.get("known")),bool(metadata.get("editable"))])
    revision=hmac.new(_focus_key,stamp.encode(),hashlib.sha256).hexdigest()[:32]
    return {"focus_known":True,"focus_editable":bool(metadata.get("editable")),"focus_revision":revision}

def exchange(value):
    wire=json.dumps(value,separators=(',',':')).encode()+b'\n'
    if len(wire)>4096:raise ValueError('Oversized desktop request')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect(str(PATH));client.sendall(wire)
        data=bytearray()
        while len(data)<=MAX_REPLY:
            part=client.recv(min(65536,MAX_REPLY+1-len(data)))
            if not part:break
            data.extend(part)
        if len(data)>MAX_REPLY:raise ValueError('Oversized desktop reply')
        return json.loads(data)

class DesktopOwner:
    def __init__(self,guard,capture,execute,clock=time.monotonic,focus_probe=focus_snapshot):
        self.guard,self.capture,self.execute,self.clock=guard,capture,execute,clock
        self.lock=threading.RLock();self.leases={}
        self.focus_probe=focus_probe

    def handle(self,value):
        with self.lock:
            now=self.clock()
            self.leases={k:v for k,v in self.leases.items() if v['until']>now}
            owner=value.get('owner','');action=value.get('action','')
            if not isinstance(owner,str) or not re.fullmatch('[0-9a-f]{64}',owner):raise ValueError('Invalid owner')
            if action=='lock':
                self.leases.pop(owner,None);return {'ok':True,'owner_enabled':False}
            if action=='unlock':
                if not self.guard():raise PermissionError('Fresh matching disarmed controller status required')
                if owner not in self.leases and len(self.leases)>=8:raise PermissionError('Owner session limit reached')
                self.leases[owner]={'until':now+300,'event':0,'last_input':0}
                return {'ok':True,'owner_enabled':True,'expires_seconds':300}
            lease=self.leases.get(owner)
            if not lease:raise PermissionError('Unlock owner access for this browser')
            if not self.guard():
                self.leases.pop(owner,None);raise PermissionError('Owner access locked: flight status is unsafe or stale')
            if action=='focus':
                return dict(ok=True,**self.focus_probe())
            if action=='frame':
                image,width,height=self.capture()
                identity=hashlib.sha256(image).hexdigest()
                result={'ok':True,'frame_id':identity,'width':width,'height':height,'expires_seconds':max(0,int(lease['until']-self.clock()))}
                if value.get('base')!=identity:result['jpeg']=base64.b64encode(image).decode()
                return result
            if action=='input':
                event=value.get('event_id')
                if type(event) is not int or not 1<=event<=9007199254740991 or event<=lease['event']:raise ValueError('Stale input event')
                command=validate_input(value.get('command'))
                expected=value.get('focus_revision')
                if "focus_revision" in value:
                    if command['type'] not in ('text','key') or not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{32}',expected):
                        raise ValueError('Invalid focused input')
                    focus=self.focus_probe()
                    if not focus['focus_known'] or not hmac.compare_digest(expected,focus.get('focus_revision') or ''):
                        lease['event']=event
                        return {'ok':True,'event_id':event,'input_applied':False}
                if now-lease['last_input']<.04:raise ValueError('Input rate limited')
                lease['event']=event;lease['last_input']=now
                self.execute(command)
                return {'ok':True,'event_id':event,'input_applied':True,'expires_seconds':max(0,int(lease['until']-self.clock()))}
            raise ValueError('Unknown desktop action')

def validate_input(value):
    if not isinstance(value,dict):raise ValueError('Invalid input')
    action=value.get('type')
    fields={'tap':{'type','x','y','button'},'drag':{'type','x','y','end_x','end_y'},'scroll':{'type','dy'},'key':{'type','key'},'text':{'type','text'}}
    if action not in fields or set(value)!=fields[action]:raise ValueError('Unsupported input')
    for key in ('x','y','end_x','end_y'):
        if key in value and (type(value[key]) is not int or not 0<=value[key]<=10000):raise ValueError('Invalid pointer coordinate')
    if action=='tap' and value['button'] not in ('left','right'):raise ValueError('Invalid button')
    if action=='scroll' and (type(value['dy']) is not int or not -8<=value['dy']<=8):raise ValueError('Invalid scroll')
    if action=='key' and value['key'] not in ('enter','escape','tab','backspace','delete','up','down','left','right','ctrl+c','ctrl+v','ctrl+a'):raise ValueError('Unsupported key')
    if action=='text' and (not isinstance(value['text'],str) or not 1<=len(value['text'])<=256 or any(c not in '\n\t' and not 32<=ord(c)<=126 for c in value['text'])):raise ValueError('Use up to 256 printable characters')
    return dict(value)

def start_bridge(owner,stop):
    slots=threading.BoundedSemaphore(3)
    def client_work(client):
        try:
            with client:
                client.settimeout(3)
                _,uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                if uid!=os.getuid():return
                wire=bytearray()
                while b'\n' not in wire and len(wire)<=4096:
                    data=client.recv(min(4096,4097-len(wire)))
                    if not data:return
                    wire.extend(data)
                if len(wire)>4096 or not wire.endswith(b'\n'):return
                try:
                    value=json.loads(wire)
                    if not isinstance(value,dict):raise ValueError('Invalid desktop request')
                    reply=owner.handle(value)
                except PermissionError as error:reply={'ok':False,'locked':True,'error':str(error)}
                except (ValueError,TypeError,RuntimeError,OSError):reply={'ok':False,'error':'Desktop request unavailable or invalid'}
                data=json.dumps(reply,allow_nan=False,separators=(',',':')).encode()
                if len(data)<=MAX_REPLY:client.sendall(data)
        except (OSError,ValueError):pass
        finally:slots.release()
    def serve():
        PATH.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(str(PATH));os.chmod(PATH,0o600);listener.listen(3);listener.settimeout(1)
            while not stop.is_set():
                try:client,_=listener.accept()
                except socket.timeout:continue
                if slots.acquire(False):threading.Thread(target=client_work,args=(client,),daemon=True).start()
                else:client.close()
    threading.Thread(target=serve,name='owner-desktop-bridge',daemon=True).start()
