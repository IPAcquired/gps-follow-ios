#!/usr/bin/python3
"""Root socket helper: stage one hotspot; activate only when offline and safe."""
import fcntl
import hashlib
import importlib.machinery
import json
import math
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time
import yaml

STATE = Path('/var/lib/orangepi-field-wifi')
PENDING = STATE/'pending.json'
MANAGED = STATE/'managed.json'
CONNECT = STATE/'connect-request.json'
CONNECT_RESULT = STATE/'connect-result.json'


def safe_flight(status, now):
    if (not isinstance(status, dict) or type(status.get('schema')) is not int or status.get('schema') != 1 or
            status.get('authority') != 'read_only_no_mavlink_transmit' or status.get('armed') is not False):
        return False
    age = status.get('updated_unix')
    if type(age) not in (int, float) or not math.isfinite(age) or not 0 <= now-age <= 3:
        return False
    if status.get('connected') is True:
        heartbeat = status.get('heartbeat_updated_unix')
        return (type(heartbeat) in (int, float) and math.isfinite(heartbeat) and
                0 <= now-heartbeat <= 2)
    # A lost established flight link never authorizes a radio reconfiguration.
    return (status.get('connected') is False and status.get('last_heartbeat_unix') is None and
            status.get('flight_session_id') is None and
            status.get('reason') in ('waiting_for_h743', 'opening_transport', 'heartbeat_not_received'))


def load_private(path, default=None):
    if not path.exists():
        return default
    info=path.lstat()
    if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Private root-owned state required')
    return json.loads(path.read_text())


def read_flight_status():
    return json.loads(Path('/run/orangepi-mavlink/status.json').read_text())


def dispatch(value, wifi):
    if not isinstance(value, dict):
        raise ValueError('Invalid request')
    action=value.get('action')
    if action == 'status' and set(value) == {'action'}:
        current=wifi.wpa_status()
        return {'ok':True, 'connected':current['state']=='COMPLETED' and bool(current['ip']),
                'ssid':current['ssid'], 'pending':PENDING.exists(), 'configured':MANAGED.exists(),
                'connect_requested':CONNECT.exists(), 'connection_result':load_private(CONNECT_RESULT,{}),
                'boot_without_upstream':True}
    if action == 'networks' and set(value) == {'action'}:
        _,aps=wifi.load_config()
        rows=[]
        for line in wifi.wpa('SCAN_RESULTS').splitlines()[1:]:
            parts=line.split('\t')
            if len(parts)<5 or 'WPA2' not in parts[3] or 'CCMP' not in parts[3]:continue
            name=wifi.decode_ssid(parts[4])
            if name and name not in [row['ssid'] for row in rows]:
                rows.append({'ssid':name,'saved':name in aps,'security':'WPA2 / CCMP'})
        return {'ok':True,'saved':[name for name,item in aps.items() if item.get('password')],
                'visible':rows[:32],'pending_ssid':load_private(PENDING,{}).get('ssid')}
    if action == 'request_connect' and set(value)=={'action','ssid'}:
        ssid=wifi.validate_ssid(value['ssid']);_,aps=wifi.load_config()
        if not (ssid in aps and aps[ssid].get('password')) and load_private(PENDING,{}).get('ssid')!=ssid:
            raise ValueError('Save a secure network first')
        if not safe_flight(read_flight_status(),time.time()):raise ValueError('Network change deferred: flight status is not safe')
        wifi.atomic_write(CONNECT,json.dumps({'ssid':ssid}).encode())
        return {'ok':True,'queued':True}
    if action != 'save_hotspot' or set(value) != {'action','ssid','password'}:
        raise ValueError('Only hotspot profile settings are accepted')
    ssid=wifi.validate_ssid(value['ssid']); password=wifi.validate_password(value['password'])
    _,aps=wifi.load_config(); managed=load_private(MANAGED, {})
    if ssid in aps and managed.get('ssid') != ssid:
        raise ValueError('That network is already managed elsewhere; its credentials were not changed')
    if len(aps) >= 64 and ssid not in aps:
        raise ValueError('Saved network limit reached')
    psk=hashlib.pbkdf2_hmac('sha1',password.encode(),ssid.encode(),4096,32).hex()
    wifi.atomic_write(PENDING,json.dumps({'ssid':ssid,'psk':psk}).encode())
    return {'ok':True, 'pending':True, 'current_connection_changed':False}


def apply_pending(wifi):
    if not PENDING.exists():
        return 'no_pending_profile'
    if wifi.wpa_status()['state'] not in ('DISCONNECTED','INACTIVE','SCANNING'):
        return 'waiting_for_upstream_disconnect'
    if any(Path(p).exists() for p in ('/run/orangepi-flight-active','/run/orangepi-maintenance-active')):
        return 'flight_or_maintenance_active'
    try:
        monitor=read_flight_status()
    except (OSError,ValueError):
        return 'flight_status_unavailable'
    if not safe_flight(monitor,time.time()):
        return 'flight_status_not_safe'
    pending=load_private(PENDING); ssid=wifi.validate_ssid(pending['ssid'])
    psk=pending['psk']
    if not isinstance(psk,str) or len(psk)!=64 or any(c not in '0123456789abcdef' for c in psk):
        raise ValueError('Invalid saved key')
    data,aps=wifi.load_config(); managed=load_private(MANAGED,{})
    if ssid in aps and managed.get('ssid')!=ssid:
        # A previous crash after atomic config write may leave an identical
        # pending profile. Reconcile it without altering another profile.
        if aps[ssid] != {'password':psk}:
            raise ValueError('Existing network requires owner review')
    if len(aps)>=64 and ssid not in aps:
        raise ValueError('Saved network limit reached')
    aps[ssid]={'password':psk}
    contents=yaml.safe_dump(data,sort_keys=False,allow_unicode=True).encode()
    with tempfile.TemporaryDirectory(prefix='validate-',dir=wifi.RUNTIME) as folder:
        root=Path(folder)
        for base in ('lib/netplan','etc/netplan','run/netplan'):
            destination=root/base; destination.mkdir(parents=True,mode=0o700)
            for source in Path('/'+base).glob('*.yaml'):
                if source.is_symlink():
                    raise ValueError('Symlinked network configuration requires review')
                wifi.atomic_write(destination/source.name,contents if source==wifi.CONFIG else source.read_bytes())
        wifi.netplan_generate(root)
    # Recheck immediately before changing the station configuration.
    if wifi.wpa_status()['state'] not in ('DISCONNECTED','INACTIVE','SCANNING'):
        return 'upstream_reconnected'
    if not safe_flight(read_flight_status(),time.time()):
        return 'flight_status_changed'
    before=wifi.CONFIG.read_bytes()
    wifi.atomic_write(STATE/'netplan-before.yaml',before)
    try:
        wifi.atomic_write(wifi.CONFIG,contents)
        wifi.netplan_generate()
        if wifi.wpa('RECONFIGURE') != 'OK' or wifi.wpa('ENABLE_NETWORK all') != 'OK':
            raise ValueError('Station did not accept saved profile')
    except Exception:
        wifi.atomic_write(wifi.CONFIG,before)
        wifi.netplan_generate()
        wifi.wpa('RECONFIGURE')
        raise
    wifi.atomic_write(MANAGED,json.dumps({'ssid':ssid,'loaded_unix':time.time()}).encode())
    PENDING.unlink()
    return 'profile_loaded'


def apply_requested_connection(wifi):
    request=load_private(CONNECT)
    if not request:return 'no_connection_request'
    if not safe_flight(read_flight_status(),time.time()):return 'waiting_for_safe_flight_status'
    if any(Path(p).exists() for p in ('/run/orangepi-flight-active','/run/orangepi-maintenance-active')):
        return 'flight_or_maintenance_active'
    ssid=wifi.validate_ssid(request['ssid']);previous=wifi.wpa_status()['ssid'];success=False
    result={'state':'failed','detail':'Connection failed; previous saved networks remain available.'}
    try:
        if load_private(PENDING,{}).get('ssid')==ssid:
            # Fixed operation used only to load a reviewed pending profile.
            client=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
            local=str(wifi.RUNTIME/('field-'+os.urandom(8).hex()))
            try:
                client.settimeout(3);client.bind(local);os.chmod(local,0o600)
                client.connect('/run/wpa_supplicant/wlan0');client.send(b'DISABLE_NETWORK all')
                if client.recv(32).strip()!=b'OK':raise ValueError('Station unavailable')
            finally:
                client.close();Path(local).unlink(missing_ok=True)
            time.sleep(.5)
            if apply_pending(wifi)!='profile_loaded':raise ValueError('Profile activation deferred')
        if not safe_flight(read_flight_status(),time.time()):raise ValueError('Flight status changed')
        ids=wifi.network_ids()
        if ssid not in ids or wifi.wpa('SELECT_NETWORK '+ids[ssid])!='OK':raise ValueError('Saved profile unavailable')
        deadline=time.monotonic()+22
        while time.monotonic()<deadline:
            current=wifi.wpa_status()
            if current['state']=='COMPLETED' and current['ssid']==ssid and current['ip']:
                success=True;result={'state':'connected','detail':'Secure Wi-Fi associated; internet access is a separate check.'};break
            time.sleep(1)
    except (OSError,ValueError):pass
    finally:
        ids=wifi.network_ids()
        if not success and previous in ids:wifi.wpa('SELECT_NETWORK '+ids[previous])
        wifi.wpa('ENABLE_NETWORK all');wifi.atomic_write(CONNECT_RESULT,json.dumps(result).encode());CONNECT.unlink(missing_ok=True)
    return result['state']


def main():
    wifi=importlib.machinery.SourceFileLoader('restricted_wifi','/usr/local/sbin/orangepi-wifi-control').load_module()
    STATE.mkdir(mode=0o700,exist_ok=True)
    with open(wifi.RUNTIME/'operation.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if sys.argv[1:]==['--apply-pending']:
            try: print(apply_requested_connection(wifi) if CONNECT.exists() else apply_pending(wifi))
            except Exception: print('Profile activation deferred; owner review needed')
            return
        if sys.argv[1:]:
            raise SystemExit(2)
        conn=socket.socket(fileno=os.dup(0)); conn.settimeout(5)
        _,uid,_=struct.unpack('3i',conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=1000:
            return
        try:
            body=b''
            while b'\n' not in body and len(body)<1024:
                part=conn.recv(1024-len(body))
                if not part:break
                body+=part
            if not body.endswith(b'\n') or len(body)>=1024:
                raise ValueError('Invalid request size')
            result=dispatch(json.loads(body),wifi)
        except ValueError as error:
            result={'ok':False,'error':str(error)}
        except Exception:
            result={'ok':False,'error':'Wi-Fi setup is unavailable; settings were not confirmed'}
        conn.sendall(json.dumps(result).encode()+b'\n')


if __name__=='__main__':
    main()
