"""Same-user, read-only snapshot bridge; no HTTP credentials or command route."""
import json, os, socket, struct, threading
from pathlib import Path

PATH=Path('/run/user/1000/axl-display-bridge/snapshot.sock')

def read_snapshot():
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(5);client.connect(str(PATH));client.sendall(b'snapshot\n')
        data=bytearray()
        while len(data)<=65536:
            part=client.recv(min(4096,65537-len(data)))
            if not part:break
            data.extend(part)
        if len(data)>65536:raise ValueError('Oversized snapshot')
        value=json.loads(data)
        if value.get('schema')!=1 or value.get('flight_control_authority') is not False:raise ValueError('Invalid read-only snapshot')
        return value

def start_snapshot_bridge(snapshot,stop):
    def serve():
        PATH.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
            listener.bind(str(PATH));os.chmod(PATH,0o600);listener.listen(2);listener.settimeout(1)
            while not stop.is_set():
                try:client,_=listener.accept()
                except socket.timeout:continue
                with client:
                    try:
                        client.settimeout(2)
                        _,uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                        if uid!=os.getuid() or client.recv(32)!=b'snapshot\n':continue
                        body=json.dumps(snapshot(),allow_nan=False,separators=(',',':')).encode()
                        if len(body)<=65536:client.sendall(body)
                    except (OSError,ValueError,TypeError):pass
    thread=threading.Thread(target=serve,name='read-only-dashboard',daemon=True);thread.start()
