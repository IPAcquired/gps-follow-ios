"""Prepare an offline R3.4 update and an exact rollback for an already paired Pi."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular_private(path):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
        raise ValueError("Expected a regular owner-only file: " + path.name)
    return path.read_bytes()


def version(content):
    hashes = {name:digest(value) for name,value in content.items()}
    return "paired-" + digest(json.dumps(hashes,sort_keys=True).encode())[:16]


def write_stage(destination, content, installer):
    destination.mkdir(mode=0o700)
    hashes = {name:digest(value) for name,value in content.items()}
    files = {**content, "sha256.json":json.dumps(hashes,sort_keys=True).encode(), "activate.py":installer}
    for name, data in files.items():
        path = destination / name
        with path.open("xb") as f:
            f.write(data)
        path.chmod(0o600)
        if regular_private(path) != data:
            raise OSError("Staging readback failed: " + name)


def prepare():
    os.umask(0o077)
    if os.getuid() == 0:
        raise PermissionError("Sign in as the ordinary owner of the existing desktop service")
    base = Path.home() / ".local/share/orange-pi-wired-desktop"
    for folder in (base,base/"releases"):
        info = folder.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Expected the existing private owner installation")
    # Serializes our snapshot with the stock installer. Prepare changes no active pointers.
    with (base/".install.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        current = base/"current"
        active = current.resolve(strict=True)
        if not current.is_symlink() or active.parent != base/"releases":
            raise ValueError("Expected the versioned current release")
        delta = json.loads((HERE/"upgrade-manifest.json").read_bytes())
        known = set(delta["original_files"]) | set(delta["updates"]) | {"approved-usb.json"}
        names = {p.name for p in active.iterdir() if p.is_file() or p.is_symlink()}
        if not names <= known or not {"launch","approved-usb.json","auto_service.py"} <= names:
            raise ValueError("Unrecognized existing release file set")
        original = {name:regular_private(active/name) for name in names}
        if active.name != version(original):
            raise ValueError("Active content differs from its immutable version")
        installer = (HERE/"pi/activate.py").read_bytes()
        if digest(installer) != delta["installer"]:
            raise ValueError("Installer hash mismatch")
        if "activate.py" in original and original["activate.py"] != installer:
            raise ValueError("Existing installer uses a different rollback format")
        proposed = original.copy()
        for name, change in delta["updates"].items():
            if name != Path(name).name or name not in known or name=="approved-usb.json":
                raise ValueError("Unexpected release member")
            prior = digest(original[name]) if name in original else None
            if prior not in change["accepted"] and prior != change["new"]:
                raise ValueError("Locally changed release file needs a manual merge: " + name)
            raw = (HERE/"pi"/name).read_bytes()
            if digest(raw) != change["new"]:
                raise ValueError("Update checksum mismatch: " + name)
            proposed[name] = raw
        if proposed == original:
            raise ValueError("This exact update is already installed")
        destination = Path(tempfile.mkdtemp(prefix="r34-update-",dir=base))
        write_stage(destination/"rollback",original,installer)
        write_stage(destination/"upgrade",proposed,installer)
        return destination


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(prepare())
