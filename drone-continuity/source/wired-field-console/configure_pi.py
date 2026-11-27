"""Commission the reusable wired display on an owner's local Orange Pi Zero 3W."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'pi'))
from bridge_usb import enumerate_bridges, pin_once, read_pin
VERSION = 'flight-team-display-1.3.34-wired-paired-r3.3'


def topology(port, identity):
    from serial.tools import list_ports
    matches = [v for v in list_ports.comports() if Path(v.device).resolve() == Path(port).resolve()
               and (v.vid, v.pid) == identity]
    if len(matches) != 1:
        raise ValueError('Selected USB port does not match the expected board.')
    root = (Path('/sys/class/tty') / Path(matches[0].device).name / 'device').resolve(strict=True)
    ancestor = next(p for p in root.parents if (p/'idVendor').exists())
    if not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*', ancestor.name):
        raise ValueError('Unexpected physical USB path.')
    return ancestor.name


def chosen_bridge(port):
    selected = Path(port).resolve(strict=True)
    bridges = enumerate_bridges()
    matches = [board for board in bridges if Path(board.node).resolve(strict=True)==selected]
    if len(matches)!=1 or sum(board.digest==matches[0].digest for board in bridges)!=1:
        raise ValueError("Select a single XIAO RP2350 with a unique readable USB identity.")
    return matches[0]


def exchange(port, action, **fields):
    ticket = secrets.randbelow(0xfffffffe)+1
    port.write((json.dumps(dict(fields, action=action, request_id=ticket))+'\n').encode())
    until = time.monotonic()+7
    while time.monotonic()<until:
        try:
            reply=json.loads(port.readline(16384))
        except (ValueError, UnicodeError):
            continue
        if isinstance(reply,dict) and reply.get('request_id')==ticket:
            return reply
    raise RuntimeError('Selected screen did not respond to the board setup request.')


def stage_and_install(usb_path):
    source=HERE/'pi'
    allowed=[p for p in source.iterdir() if p.suffix=='.py' or p.name in ('launch','discovery.service','README.txt')]
    (Path.home()/'.local/bin').mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wireddisplay-') as directory:
        stage=Path(directory)
        data={p.name:p.read_bytes() for p in allowed}
        data['approved-usb.json']=json.dumps({'topology':usb_path}).encode()
        for name,body in data.items():
            path=stage/name;path.write_bytes(body);path.chmod(0o700 if name=='launch' else 0o600)
        (stage/'sha256.json').write_text(json.dumps({n:hashlib.sha256(v).hexdigest() for n,v in data.items()}))
        subprocess.run([sys.executable,'-B',str(stage/'activate.py'),'activate'],check=True)


def owner_broker_path():
    return Path('/run/user')/str(os.getuid())/'axl-display-bridge/desktop.sock'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screen-port',required=True,help='On this Pi, the LCD board CH340 USB port during commissioning')
    parser.add_argument('--bridge-port',help='On this Pi, the XIAO USB CDC port. If omitted, approve the current screen port for direct-only use.')
    parser.add_argument('--configure-network-policy',action='store_true',help='Provision the owner-supplied pinned private TLS/QR names and home SSID once')
    args=parser.parse_args()
    if sys.platform!='linux':raise RuntimeError('Run this installer on the Orange Pi under Linux.')
    if os.getuid()==0:raise PermissionError('Run from the local graphical desktop owner account.')
    os.umask(0o077)
    screen_path=topology(args.screen_port,(0x1a86,0x7523))
    bridge=chosen_bridge(args.bridge_port) if args.bridge_port else None
    bridge_path=bridge.topology if bridge else screen_path
    profile=Path.home()/'.config/orange-pi-wired-desktop'
    if bridge and read_pin(profile/'xiao-serial.sha256') not in (None,bridge.digest):
        raise PermissionError('Another XIAO is already enrolled. Use the existing bridge or owner recovery.')
    broker=owner_broker_path()
    if not broker.is_socket():raise RuntimeError('The compatible local owner desktop broker must be installed and running first.')
    peer=broker.lstat()
    if not stat.S_ISSOCK(peer.st_mode) or peer.st_uid!=os.getuid() or stat.S_IMODE(peer.st_mode)!=0o600:
        raise PermissionError('The local desktop broker must be owned by the current user and have mode 0600.')
    import serial
    port=serial.Serial(port=None,baudrate=115200,timeout=.25,write_timeout=1,exclusive=True)
    port.dtr=False;port.rts=False;port.port=args.screen_port
    with port:
        info=exchange(port,'wired_status')
        ident=info.get('screen_mac')
        if (info.get('display')!='Hosyond-E32R35T' or info.get('firmware')!=VERSION or
                not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{12}',ident)):
            raise ValueError('Screen model or application version differs from this release.')
        if info.get('paired') and not any((profile/f).is_file() for f in ('pair.key','.pending-screen-pair/pair.key')):
            raise PermissionError('This screen is already paired. Restore its original owner pairing or perform owner recovery.')
        bind=bytes.fromhex(ident)+screen_path.encode()
        registrar=[sys.executable,'-B',str(HERE/'pi_pair_provision.py')]
        key=subprocess.run(registrar+['prepare'],input=bind,capture_output=True,check=True).stdout
        if len(key)!=32:raise RuntimeError('Creating the private Pi binding failed.')
        if not info.get('paired'):
            result=exchange(port,'wired_pair_enroll',target=VERSION,confirm='PAIR_THIS_SCREEN_ONCE',key_hex=key.hex())
            if result.get('accepted') is not True:raise PermissionError('Screen enrollment was declined.')
        del key
        check=exchange(port,'wired_status')
        if check.get('paired') is not True or check.get('screen_mac')!=ident:
            raise RuntimeError('Screen enrollment readback failed.')
        if args.configure_network_policy and not check.get('local_setup'):
            dns=input('Private .local hostname on your existing trusted Pi certificate: ').strip()
            ssid=input('Wi-Fi name approved for maintenance: ').strip()
            result=exchange(port,'wired_local_setup',target=VERSION,confirm='SET_LOCAL_IDENTITIES_ONCE',
                            tls_dns=dns,dashboard_origin='https://'+dns+':8446',home_ssid=ssid)
            if result.get('accepted') is not True:raise RuntimeError('Screen did not accept the local network policy.')
        subprocess.run(registrar+['activate'],input=bind,capture_output=True,check=True)
    if bridge:
        if chosen_bridge(args.bridge_port)!=bridge:
            raise RuntimeError('The selected XIAO changed during commissioning. Recheck the cable and run setup again.')
        pin_once(profile/'xiao-serial.sha256',bridge.digest)
    stage_and_install(bridge_path)
    print('Owner service installed. Its status confirms the first mutually authenticated desktop after attachment.')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,PermissionError,RuntimeError,subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
