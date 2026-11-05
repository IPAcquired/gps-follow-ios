#!/usr/bin/python3
"""Preserve Armbian USB quirks without rewriting boot configuration every boot."""
import fcntl
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

DEFAULTS = '0x2537:0x1066:u,0x2537:0x1068:u'

def desired_config(original, usb_listing):
    lines = original.splitlines(keepends=True)
    current = [line.split('=', 1)[1].strip() for line in lines
               if line.startswith('usbstoragequirks=')]
    quirks = ','.join(filter(None, current)) or DEFAULTS
    for vendor, product in sorted(set(re.findall(r'\bID\s+(0bc2|1058):([0-9a-fA-F]{4})\b', usb_listing))):
        identity = '0x' + vendor + ':0x' + product.lower()
        if not any(item.lower().startswith(identity + ':') for item in quirks.split(',')):
            quirks += ',' + identity + ':u'
    if len(current) == 1 and current[0] == quirks:
        return original, quirks
    result = ''.join(line for line in lines if not line.startswith('usbstoragequirks='))
    if result and not result.endswith('\n'):
        result += '\n'
    return result + 'usbstoragequirks=' + quirks + '\n', quirks

def save_if_changed(path, original, updated):
    if original == updated:
        return False
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('Boot configuration must be a regular file')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            stream.write(updated.encode('utf-8'))
            stream.flush()
            os.fsync(stream.fileno())
        # Avoid overwriting a concurrent configuration edit.
        if path.read_text(encoding='utf-8') != original:
            raise RuntimeError('Boot configuration changed during update')
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True

def main():
    path = Path('/boot/armbianEnv.txt')
    if not path.exists():
        return
    with open('/run/lock/axl-usb-storage-quirks.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Unsafe boot configuration ownership or type')
        original = path.read_text(encoding='utf-8')
        try:
            listing = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5, check=True).stdout
        except (OSError, subprocess.SubprocessError):
            listing = ''  # Preserve existing quirks if USB discovery is unavailable.
        updated, quirks = desired_config(original, listing)
        save_if_changed(path, original, updated)
        runtime = Path('/sys/module/usb_storage/parameters/quirks')
        if runtime.exists() and runtime.read_text().strip() != quirks:
            runtime.write_text(quirks + '\n')

if __name__ == '__main__':
    main()
