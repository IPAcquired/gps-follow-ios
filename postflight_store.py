"""Private DataFlash intake, shared by the mounted-card and onboard read-only sources."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time


NAME = re.compile(r"[0-9]{1,10}\.BIN", re.IGNORECASE)
LIMIT = 512 * 1024 * 1024
RESERVE = 1024 * 1024 * 1024


class Deferred(ValueError):
    pass


def private(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or path != path.resolve():
        raise Deferred("private_storage_unavailable")
    return path


def publish_json(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
        temp = Path(out.name)
        try:
            json.dump(value, out, sort_keys=True, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally: temp.unlink(missing_ok=True)


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


class Intake:
    def __init__(self, home):
        self.home = home
        self.root = private(home/"flight-data/acquisition")
        self.snapshots = private(self.root/"snapshots")
        self.entries = private(self.root/"sources")
        self.inbox = private(home/"flight-data/inbox")

    def reserve(self, size):
        if not 0 < size <= LIMIT or shutil.disk_usage(self.root).free < size + RESERVE:
            raise Deferred("file_limit_or_free_space")

    def copy(self, origin, name, size, chunks, validate, final, session=None):
        if not NAME.fullmatch(name):
            raise Deferred("invalid_log_name")
        self.reserve(size)
        key = hashlib.sha256((origin+"\0"+name.upper()).encode()).hexdigest()
        history = self.entries/(key+".json")
        previous = json.loads(history.read_bytes()) if history.exists() else {}
        with tempfile.NamedTemporaryFile(dir=self.snapshots, delete=False) as sink:
            temp = Path(sink.name)
            try:
                digest = hashlib.sha256()
                total = 0
                for data in chunks:
                    if not data or total+len(data)>size:
                        raise Deferred("inconsistent_source_length")
                    sink.write(data);digest.update(data);total+=len(data)
                if total != size or not validate():
                    raise Deferred("source_changed")
                sink.flush();os.fsync(sink.fileno())
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            with temp.open("rb") as src:
                if src.read(3) != b"\xa3\x95\x80":
                    raise Deferred("invalid_dataflash_header")
            sha=digest.hexdigest()
            snapshot=self.snapshots/(sha+".BIN")
            if not snapshot.exists():
                os.link(temp,snapshot)
            elif snapshot.stat().st_size!=size or file_hash(snapshot)!=sha:
                raise Deferred("private_snapshot_checksum_mismatch")
            # A single file can span several arm/disarm cycles. Keep unclosed versions
            # separate from the analyzer corpus until a successor or offline mount proves closure.
            queued = bool(previous.get("queued") and previous.get("sha256")==sha)
            if final and not queued:
                if previous.get("queued") and previous.get("sha256")!=sha and size>=previous["bytes"]:
                    with snapshot.open("rb") as src:
                        prefix=hashlib.sha256()
                        left=previous["bytes"]
                        while left:
                            data=src.read(min(left,1024*1024));prefix.update(data);left-=len(data)
                    if prefix.hexdigest()==previous["sha256"]:
                        raise Deferred("previously_finalized_log_grew_manual_review")
                inbox=self.inbox/("fc-"+sha+".BIN")
                try: os.link(snapshot,inbox)
                except FileExistsError:
                    if inbox.stat().st_size!=size or file_hash(inbox)!=sha:raise Deferred("inbox_conflict")
                queued=True
            record={"schema":1,"sha256":sha,"bytes":size,"queued":queued,
                    "classification":"closed" if final else "stable_snapshot","flight_session":session}
            publish_json(history,record)
            return record
        finally:
            temp.unlink(missing_ok=True)


def mounted(intake, logdir, origin):
    logdir=Path(logdir)
    if logdir.resolve()!=logdir or logdir.name.upper()!="LOGS" or logdir.parent.name.upper()!="APM":
        raise Deferred("expected_fc_card_apm_logs")
    if not os.path.ismount(logdir.parent.parent) or not os.statvfs(logdir).f_flag&os.ST_RDONLY:
        raise Deferred("mount_fc_card_read_only")
    count=0
    for path in sorted(logdir.iterdir()):
        if not NAME.fullmatch(path.name):continue
        fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        with os.fdopen(fd,"rb") as src:
            before=os.fstat(src.fileno())
            if not stat.S_ISREG(before.st_mode):continue
            def unchanged():
                st=path.stat(follow_symlinks=False)
                return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)
            intake.copy(origin,path.name,before.st_size,iter(lambda:src.read(256*1024),b""),unchanged,True)
            count+=1
    return count
