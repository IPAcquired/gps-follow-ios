"""Create an owner-private review proposal for two root-owned legacy routes."""
import hashlib,json,os,re,sys
from pathlib import Path

def candidate(config,rule):
    if (config.get("schema")!=1 or config.get("mavlink_transmit_enabled") is not False
          or config.get("parameter_writes_enabled") is not False):
        raise ValueError("Unexpected monitor policy.")
    rows=config.get("transports",[])
    expected={'identified_h743_usb':('/dev/h743-usb','serial'), 'micoair_bluetooth':('/dev/rfcomm0','bluetooth_rfcomm')}
    known={r.get('name'):r for r in rows if isinstance(r,dict)}
    if len(known)!=len(rows) or any((known.get(k,{}).get('device'),known.get(k,{}).get('kind'))!=v for k,v in expected.items()):
        raise ValueError("Legacy route definitions have changed. Review required.")
    if (known.get('wired_h743',{}).get('device')!='/dev/h743' or known['wired_h743'].get('baud')!=115200 or
        known.get('authenticated_pc_usb',{}).get('device')!='/run/orangepi-mavlink/pc-h743.fifo'):
        raise ValueError("Existing approved wired routes must be preserved.")
    statements=[line for line in rule.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if len(statements)!=1 or 'ATTRS{product}=="MicoAir743v2"' not in statements[0] or 'SYMLINK+="h743-usb"' not in statements[0]:
        raise ValueError("USB rule differs from the reviewed old product rule.")
    return {**config,'transports':[r for r in rows if r['name'] not in expected]}, (
        "# The legacy product-specific USB fallback is retired.\n"
        "# Keep direct USB unavailable until a separately reviewed rule matches\n"
        "# the installed CORVON product and its privately verified USB serial.\n")

if __name__=='__main__':
    os.umask(0o077)
    folder=Path(sys.argv[1]).resolve()
    if folder.stat().st_uid!=os.getuid() or folder.stat().st_mode&0o077:
        raise PermissionError('Proposal directory must be private to its owner.')
    sources=(Path('/etc/orangepi-mavlink-monitor.json'),Path('/etc/udev/rules.d/98-axl-h743-usb.rules'))
    original=[p.read_bytes() for p in sources]
    cfg,rule=candidate(json.loads(original[0]),original[1].decode())
    new=(json.dumps(cfg,indent=2).encode()+b'\n',rule.encode())
    manifest=[]
    for p,old,data in zip(sources,original,new):
        (folder/(p.name+'.proposed')).write_bytes(data)
        manifest.append({'target':str(p),'before_sha256':hashlib.sha256(old).hexdigest(),
                         'candidate_sha256':hashlib.sha256(data).hexdigest()})
    (folder/'review.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Prepared two review-only candidates. Native and identity-bound PC routes retained. No services changed.')
