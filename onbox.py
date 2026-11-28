"""Verify, stage, switch or restore one matched sender using the RC6 installer."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
UNIT = "orange-pi-wired-desktop-discovery.service"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private(path, directory=False):
    mode = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    require(kind(mode.st_mode) and mode.st_uid == os.getuid() and not mode.st_mode & 0o077,
            "Expected an owner-private " + ("directory." if directory else "file."))


def inventory(folder):
    private(folder, directory=True)
    result = {}
    for f in folder.iterdir():
        private(f)
        result[f.name] = sha(f.read_bytes())
    return result


def version(manifest):
    return "paired-" + sha(json.dumps(manifest, sort_keys=True).encode())[:16]


def stage_path(output, base):
    result = Path(output)
    require(result.parent == base and re.fullmatch(r"r34-update-[a-zA-Z0-9_-]+", result.name)
            and result.resolve(strict=True) == result, "Unexpected staging location.")
    private(result, directory=True)
    return result


def run(*argv):
    result = subprocess.run(list(argv), check=True, timeout=210, text=True, stdout=subprocess.PIPE)
    return result.stdout.strip()


def stock_source(kit):
    lines = (kit / "rc6-source.sha256").read_text(encoding="ascii").splitlines()
    match = [re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line) for line in lines]
    require(len(lines) == 32 and all(match), "Unexpected RC6 source inventory.")
    result = {m[2]:m[1] for m in match}
    require(len(result) == 32, "Duplicate RC6 source entry.")
    return result


def verify_kit(kit):
    lines = (kit / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    for line in lines:
        m = re.fullmatch(r"([a-f0-9]{64})  ((?:pi/)?[A-Za-z0-9_.-]+)", line)
        require(m and sha((kit / m[2]).read_bytes()) == m[1], "Kit checksum failed.")
    update = json.loads((kit / "upgrade-manifest.json").read_bytes())
    require(sha((kit / "pi/activate.py").read_bytes()) == update["installer"], "Installer changed.")
    return update


def stage_inventory(stage, source, changes, installer_hash):
    manifest = {}
    for side in ("rollback", "upgrade"):
        folder = stage / side
        actual = inventory(folder)
        require(actual.pop("activate.py") == installer_hash, "Staged installer differs.")
        actual.pop("sha256.json")
        require(actual == json.loads((folder / "sha256.json").read_bytes()), "Staged inventory differs.")
        manifest[side] = actual
    stock = manifest["rollback"].copy()
    require(set(stock) == set(source) | {"approved-usb.json"}, "Rollback inventory differs.")
    require(all(stock[n] == h for n,h in source.items()), "Rollback differs from RC6 source.")
    for name, change in changes.items():
        require([stock[name]] == change["accepted"], "Unexpected base module.")
        stock[name] = change["new"]
    require(stock == manifest["upgrade"], "Staged candidate or enrollment differs.")
    return manifest


def read_current(base, releases):
    current = base / "current"
    target = current.resolve(strict=True)
    require(current.is_symlink() and target.parent == releases, "Unexpected current release.")
    data = inventory(target)
    require(target.name == version(data), "Active release version or contents changed.")
    return target, data


def save_stage(journal, stage):
    with tempfile.NamedTemporaryFile(mode="w", dir=journal.parent, delete=False) as stream:
        tmp = Path(stream.name)
        try:
            stream.write(stage.name + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, journal)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_service():
    for args, expected in ((("is-active", UNIT), "active"), (("is-enabled", UNIT), "enabled"),
                           (("show", UNIT, "-p", "RestrictAddressFamilies", "--value"), "AF_UNIX")):
        require(run("/usr/bin/systemctl", "--user", *args) == expected, "Owner service verification failed.")


def operate(action, kit=HERE):
    require(os.getuid() != 0, "Run as the signed-in desktop owner.")
    os.umask(0o077)
    base = Path.home() / ".local/share/orange-pi-wired-desktop"
    releases = base / "releases"
    private(base, directory=True)
    private(releases, directory=True)
    update = verify_kit(kit)
    source = stock_source(kit)
    journal = base / (".sender-kit-stage-" + sha((kit / "upgrade-manifest.json").read_bytes()))
    with (base / ".sender-kit-switch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active, current = read_current(base, releases)
        if journal.exists():
            private(journal)
            stage = stage_path(base / journal.read_text().strip(), base)
        else:
            require(action == "prepare", "Run prepare for this kit first.")
            require(set(current) == set(source) | {"approved-usb.json"} and
                    all(current[n] == h for n,h in source.items()), "Preparation requires the full RC6 source.")
            stage = stage_path(run(sys.executable, "-B", str(kit / "upgrade_existing.py")), base)
        sides = stage_inventory(stage, source, update["updates"], update["installer"])
        original = releases / version(sides["rollback"])
        require(inventory(original) == sides["rollback"], "Immutable RC6 fallback differs.")
        require(current in sides.values(), "A different enrolled sender is active.")
        if not journal.exists():
            save_stage(journal, stage)
        if action == "prepare":
            require(current == sides["rollback"], "Restore RC6 before preparing another trial.")
            run(sys.executable, "-B", str(stage / "upgrade/activate.py"), "stage")
        elif action in ("activate", "rollback"):
            side = "upgrade" if action == "activate" else "rollback"
            if current != sides[side]:
                run(sys.executable, "-B", str(stage / side / "activate.py"), "activate")
            active, current = read_current(base, releases)
            require(current == sides[side] and inventory(original) == sides["rollback"],
                    "Release or fallback readback differs.")
            ensure_service()
        state = "rc6" if current == sides["rollback"] else "selected"
        print(json.dumps(dict(action=action, installed=state, current=str(active), fallback=str(original),
                              stage=str(stage), files=len(current), modules=sorted(update["updates"]))))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("prepare", "activate", "status", "rollback"))
    operate(p.parse_args().action)
