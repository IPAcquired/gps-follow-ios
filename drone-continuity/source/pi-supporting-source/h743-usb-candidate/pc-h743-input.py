"""Feed SSH stdin into one private receive-only MAVLink FIFO. No flight writes."""
import fcntl
import os
from pathlib import Path
import select
import stat
import sys
import time
from pc_bridge_frame import decode_frame

path=Path('/run/orangepi-mavlink/pc-h743.fifo')
lock=os.open(str(path)+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
info=os.fstat(lock)
assert stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode&0o077
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
try:os.mkfifo(path,0o600)
except FileExistsError:pass
info=path.lstat()
assert stat.S_ISFIFO(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode&0o077
identity=(info.st_dev,info.st_ino)
fd=None
buffer=b''
sequence=0
last_input=time.monotonic()
try:
    while True:
        info=path.lstat()
        if (info.st_dev,info.st_ino)!=identity:break
        if not select.select([sys.stdin.buffer],[],[],2)[0]:
            if time.monotonic()-last_input>10:break
            continue
        chunk=os.read(sys.stdin.fileno(),4096)
        if not chunk:break
        last_input=time.monotonic()
        buffer+=chunk
        if len(buffer)>16384:raise ValueError('Input bound')
        while b'\n' in buffer:
            line,buffer=buffer.split(b'\n',1)
            try:sequence,data=decode_frame(line,time.time(),sequence)
            except ValueError:continue
            if fd is None:
                try:fd=os.open(path,os.O_WRONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
                except OSError:continue
            try:os.write(fd,data)
            except BlockingIOError:pass  # Drop bounded chunks; never buffer stale samples.
            except BrokenPipeError:os.close(fd);fd=None
finally:
    if fd is not None:os.close(fd)
    try:
        info=path.lstat()
        if (info.st_dev,info.st_ino)==identity:path.unlink()
    except FileNotFoundError:pass
    os.close(lock)
