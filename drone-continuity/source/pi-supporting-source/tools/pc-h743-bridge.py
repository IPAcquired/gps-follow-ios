"""Automatic receive-only H743 USB -> pinned SSH -> Pi -> ESP32 bridge."""
import base64,ctypes,json,os,pathlib,subprocess,sys,time
from ctypes import wintypes
sys.path.insert(0,r'C:\Users\Daddy Nate\Documents\Codex\2026-10-09\referenced-chatgpt-conversation-this-is-an\work\esp32-tools-20261021')
import serial
from serial.tools import list_ports
root=pathlib.Path(__file__).resolve().parents[1]
state_dir=root/'work/private/h743-power-check';state_dir.mkdir(exist_ok=True)
stop=state_dir/'bridge.stop'
ctypes.windll.kernel32.CreateMutexW.argtypes=[wintypes.LPVOID,wintypes.BOOL,wintypes.LPCWSTR]
ctypes.windll.kernel32.CreateMutexW.restype=wintypes.HANDLE
ctypes.windll.kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\AXL_H743_PC_RECEIVE_ONLY')
if not mutex:raise OSError('Cannot acquire bridge mutex')
if ctypes.windll.kernel32.GetLastError()==183:raise SystemExit('Bridge already running')
(state_dir/'bridge.pid').write_text(str(os.getpid()))
ssh=['ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=5','-o','ServerAliveInterval=3','-o','ServerAliveCountMax=2','-o','StrictHostKeyChecking=yes','-o','HostKeyAlias=192.168.0.132','-o','HostKeyAlgorithms=ssh-ed25519','-o','KexAlgorithms=curve25519-sha256','-o','IdentitiesOnly=yes','-i',r'C:\Users\Daddy Nate\.ssh\orangepi_drone_ed25519','drone@192.168.1.176','python3 /home/drone/bin/pc-h743-input.py']
destinations=['192.168.1.176','example-pi.local','192.0.2.10']
target_index=0
def publish(state,**fields):
    value=dict(state=state,updated_unix=time.time(),pid=os.getpid(),serial_writes=0,**fields)
    target=state_dir/'bridge-status.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(value));os.replace(temp,target)
try:
    while not stop.exists():
        matches=[p for p in list_ports.comports() if p.vid==0x1209 and p.pid==0x5741 and p.serial_number=='40004C000D51333332333430']
        if len(matches)!=1:publish('waiting_for_identified_h743_usb');time.sleep(2);continue
        port=serial.Serial(port=None,baudrate=115200,timeout=.2)
        port.dtr=False;port.rts=False;port.port=matches[0].device
        child=None;sent=0;sequence=0;last_publish=0;last_read=time.monotonic()
        try:
            port.open();port.reset_input_buffer()
            command=list(ssh);command[-2]='drone@'+destinations[target_index]
            child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            while not stop.exists() and child.poll() is None:
                if time.monotonic()-last_read>2 or port.in_waiting>8192:port.reset_input_buffer()
                data=port.read(min(4096,max(1,port.in_waiting)));last_read=time.monotonic()
                if data:
                    sequence+=1
                    frame=dict(seq=sequence,received_unix=time.time(),data=base64.b64encode(data).decode())
                    child.stdin.write(json.dumps(frame,separators=(',',':')).encode()+b'\n');child.stdin.flush();sent+=len(data)
                if time.monotonic()-last_publish>2:
                    publish('forwarding_usb_bytes',port=port.port,bytes_forwarded=sent,heartbeat_validation='Pi monitor, not this sender')
                    last_publish=time.monotonic()
        except (OSError,serial.SerialException):publish('reconnecting')
        finally:
            port.close()
            if child is not None:
                try:
                    if child.stdin:child.stdin.close()
                except OSError:pass
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.terminate();child.wait(timeout=3)
        time.sleep(2)
        target_index=(target_index+1)%len(destinations)
finally:
    publish('stopped');ctypes.windll.kernel32.CloseHandle(mutex)
