"""Install, check or restore the paired desktop viewport update on the Orange Pi."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


FILES = ("desktop_workspace.py", "desktop_capture.py")
SERVICE = "orangepi-companion.service"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def transform(data, change, target):
    if target == "installed":
        source, source_start, destination = "original", "old_line", "installed"
    else:
        source, source_start, destination = "installed", "new_line", "original"
    if digest(data) == change[target]:
        return data
    if digest(data) != change[source]:
        raise ValueError("Installed file differs from both reviewed versions.")
    lines = data.decode("utf-8").splitlines(keepends=True)
    for hunk in reversed(change["edits"]):
        offset = hunk[source_start]
        old = hunk[source].splitlines(keepends=True)
        if lines[offset:offset + len(old)] != old:
            raise ValueError("Source at the recorded line differs.")
        lines[offset:offset + len(old)] = hunk[destination].splitlines(keepends=True)
    result = "".join(lines).encode("utf-8")
    if digest(result) != change[target]:
        raise ValueError("Patched file differs from its release digest.")
    return result


def replace(path, data, metadata):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".viewport-")
    try:
        with os.fdopen(fd, "wb") as stream:
            current = os.fstat(stream.fileno())
            if metadata.st_gid != current.st_gid:
                os.fchown(stream.fileno(), -1, metadata.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def restart():
    for args in (["restart", SERVICE], ["is-active", "--quiet", SERVICE]):
        subprocess.run(["systemctl", "--user", *args], check=True, timeout=40)


def update(mode, directory, changes):
    import fcntl

    if set(changes) != set(FILES):
        raise ValueError("The package has unexpected module names.")
    uid = os.getuid()
    if uid == 0:
        raise PermissionError("Run as the graphical desktop owner.")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(descriptor)
        if meta.st_uid != uid or meta.st_mode & 0o022:
            raise PermissionError("The owner bin directory must be owner-controlled.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        target = "installed" if mode == "install" else "original"
        steps = []
        observed = {}
        for name in FILES:
            path = directory / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != uid or metadata.st_mode & 0o022:
                raise PermissionError("Expected an owner-controlled regular module: " + name)
            current = path.read_bytes()
            checksum = digest(current)
            change = changes[name]
            if checksum == change["original"]:
                observed[name] = "original"
            elif checksum == change["installed"]:
                observed[name] = "installed"
            else:
                raise ValueError("Unrecognized installed source: " + name)
            if mode != "check" and observed[name] != target:
                new = transform(current, change, target)
                compile(new, name, "exec")
                steps.append((path, current, new, metadata))
        if mode == "check":
            return observed
        if steps and mode == "restore":
            steps.reverse()
        completed = []
        try:
            for path, current, new, metadata in steps:
                if path.read_bytes() != current:
                    raise RuntimeError("Module changed during update: " + path.name)
                replace(path, new, metadata)
                completed.append((path, current, new, metadata))
            os.fsync(descriptor)
            # An interrupted prior run may already have replaced both files.
            restart()
        except BaseException:
            for path, current, new, metadata in reversed(completed):
                if path.read_bytes() != new:
                    raise RuntimeError("External edit encountered during rollback: " + path.name)
                replace(path, current, metadata)
            os.fsync(descriptor)
            if completed:
                restart()
            raise
        return dict.fromkeys(FILES, target)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "install", "restore"))
    args = parser.parse_args()
    changes = json.loads(Path(__file__).with_name("display-edits.json").read_bytes())
    for name, state in update(args.mode, Path.home() / "bin", changes).items():
        print(name, state)
