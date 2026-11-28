"""Install or restore the paired E32R35T app over its approved Pi USB socket."""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
APP = 0x10000
CAPACITY = 4 * 1024 * 1024
APP_SIZE = 0x1e0000
TABLE_SHA = "0a8b5720e7b77ff11f1462458c3a509dee79224e5279898f26d6a2e3ae0517b7"
PRIOR_SHA = "d5c91a63a439b3298212621d694ac7516e8001a041b24795fbcabc523bfd0bf1"
SERVICE = "orange-pi-wired-desktop-discovery.service"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def md5(data):
    return hashlib.md5(data).hexdigest()


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def atomic_private(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            name = stream.name
        except BaseException:
            Path(stream.name).unlink(missing_ok=True)
            raise
    try:
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def private_bytes(path):
    meta = path.lstat()
    require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid() and not meta.st_mode & 0o077,
            "Recovery file must be private and owner-controlled.")
    return path.read_bytes()


def verify_guard():
    s = json.loads(Path("/run/orangepi-mavlink/status.json").read_bytes())
    require(s.get("connected") and s.get("armed") is False
            and 0 <= time.time() - s.get("heartbeat_updated_unix", 0) <= 2,
            "A fresh disarmed controller is required.")


def app_files():
    directory = HERE / "firmware"
    old = (directory / "stock.bin").read_bytes()
    new = (directory / "trial.bin").read_bytes()
    table = (directory / "reference-partitions.bin").read_bytes()
    require(sha(old) == PRIOR_SHA and sha(table) == TABLE_SHA and sha(new) == '5e4bf910726c01ad6004d71516fec754752aa4e54bf5a8d43204697b59c0a4c3',
            "Release image or partition checksum differs.")
    span = (max(len(old), len(new)) + 4095) // 4096 * 4096
    require(0 < span <= APP_SIZE and old[:1] == new[:1] == b'\xe9'
            and b"wired_geometry_version" in new, "Unexpected application image.")
    return old, new, table, span


def check_layout(stub, table):
    require(stub.read_flash(0x8000, len(table)) == table, "Partition table differs.")
    slots = []
    for pos in range(0, len(table) - 31, 32):
        magic, kind, subtype, offset, size = struct.unpack_from("<HBBII", table, pos)
        if magic != 0x50aa:
            break
        if kind == 0:
            slots.append((offset, size))
    require((APP, APP_SIZE) in slots, "The expected app0 partition is missing.")
    for offset, _ in slots:
        if offset != APP:
            require(stub.read_flash(offset, 4)[:1] != b'\xe9', "Alternate bootable application found.")


class StatusUnavailable(TimeoutError):
    """The application's correlated status replies did not arrive in time."""


def guarded_wait(seconds):
    end = time.monotonic() + seconds
    while True:
        verify_guard()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, .2))


def probe(port, binding):
    from direct_usb import DirectTimeout, open_direct

    # Discovery may have just released a high-baud session, or the ROM loader
    # just reset the screen. Let the firmware's idle watchdog and normal UI run.
    guarded_wait(3.0)
    deadline = time.monotonic() + 30.0
    busy = False
    with open_direct(port, binding, verify_guard) as wire:
        identified = False
        while time.monotonic() < deadline:
            verify_guard()
            try:
                if not identified:
                    wire.begin()
                    identified = True
                status = wire.request("wired_status", min(deadline, time.monotonic() + 2.5))
                require(status.get("display") == "Hosyond-E32R35T" and status.get("screen_mac") == binding.hex()
                        and status.get("paired") is True and status.get("local_setup") is True
                        and status.get("staging_slice_version") == 2, "Enrolled display or firmware differs.")
                busy = status.get("guard") is not False or status.get("desktop_live") is not False
                if busy:
                    guarded_wait(.3)
                    continue
                detail = wire.request("status", min(deadline, time.monotonic() + 4.0))
            except DirectTimeout:
                guarded_wait(.3)
                continue
            require(detail.get("touch_calibrated") is True, "Touch calibration is missing.")
            require(detail.get("display") == status["display"] and detail.get("firmware") == status.get("firmware")
                    and detail.get("wired_paired") is True and detail.get("local_setup") is True,
                    "General status does not match the enrolled wired display.")
            version = status.get("wired_geometry_version")
            require(version in (None, 1), "Unexpected display geometry protocol.")
            verify_guard()
            return version
    require(not busy, "The local display did not become idle.")
    raise StatusUnavailable("The enrolled screen did not return both status replies in time.")


@contextlib.contextmanager
def loader(port, binding):
    from esptool import cmds
    from esptool.targets.esp32 import ESP32ROM

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with ESP32ROM(port, 115200) as rom:
            try:
                rom.connect(attempts=3)
                require(bytes(rom.read_mac()) == binding, "ROM device identity differs.")
                require(not rom.secure_download_mode and not rom.get_flash_encryption_enabled()
                        and not rom.get_secure_boot_enabled(), "Flash protections differ.")
                stub = rom.run_stub()
                require(cmds.detect_flash_size(stub) == "4MB", "Flash capacity differs.")
                stub.change_baud(460800)
                yield stub
            finally:
                with contextlib.suppress(Exception):
                    rom.hard_reset()


def write_app(stub, data, span):
    from esptool import cmds

    verify_guard()
    outside = ((0, APP), (APP + span, CAPACITY - APP - span))
    prior = [stub.flash_md5sum(offset, length).lower() for offset, length in outside]
    stream = io.BytesIO(data)
    stream.name = "screen-app.bin"
    options = SimpleNamespace(addr_filename=[(APP, stream)], compress=True, no_compress=False, no_stub=False,
                              force=False, encrypt=False, encrypt_files=None, erase_all=False,
                              ignore_flash_encryption_efuse_setting=False, flash_size="keep", flash_freq="keep",
                              flash_mode="keep", chip="esp32")
    verify_guard()
    cmds.write_flash(stub, options)
    require(stub.flash_md5sum(APP, len(data)).lower() == md5(data), "Application readback differs.")
    require(prior == [stub.flash_md5sum(offset, length).lower() for offset, length in outside],
            "Flash outside the application sectors changed.")


def service(*args, check=True):
    return subprocess.run(["systemctl", "--user", *args, SERVICE], timeout=35, check=check)


def transaction(mode, state, binding):
    from direct_usb import find_direct

    old, new, table, span = app_files()
    path = state / "transaction.json"
    backup = state / "original-app-sectors.bin"
    identity = dict(device=sha(binding), candidate=sha(new), original=PRIOR_SHA, span=span)
    history = json.loads(private_bytes(path)) if path.exists() else None
    if history is not None:
        require(all(history.get(k) == v for k, v in identity.items()), "Recovery identity differs.")
    saved = private_bytes(backup) if backup.exists() else None
    if saved is not None:
        require(len(saved) == span and saved[:len(old)] == old, "Invalid saved application.")
        if history is not None:
            require(sha(saved) == history.get("backup"), "Saved recovery digest differs.")
    require(not history or saved is not None, "Transaction recovery backup is missing.")
    require(mode == "install" or (saved is not None and history is not None), "No verified local backup.")
    def record(phase):
        atomic_private(path, json.dumps(dict(identity, backup=sha(saved), phase=phase)).encode())
    port, cookie = find_direct(binding)
    def attached():
        require(port and cookie and find_direct(binding) == (port, cookie), "Approved USB attachment changed.")
    attached()
    verify_guard()
    was_active = service("is-active", "--quiet", check=False).returncode == 0
    require(was_active or mode == "restore", "The paired display service is inactive.")
    if was_active:
        service("stop")
    started = False
    try:
        interrupted = bool(history and history.get("phase") in ("writing", "restoring"))
        require(not interrupted or mode == "restore", "Finish interrupted recovery using restore.")
        verify_installed_rom = False
        if not interrupted:
            try:
                probe(port, binding)
            except StatusUnavailable:
                if mode != "restore" or not history or history.get("phase") != "installed":
                    raise
                # The bound unit's verified application can fail to answer later.
                # Recover from this state only after checking the exact RC6 bytes.
                verify_installed_rom = True
        attached()
        verify_guard()
        with loader(port, binding) as stub:
            check_layout(stub, table)
            original_app = stub.flash_md5sum(APP, len(old)).lower() == md5(old)
            candidate_app = stub.flash_md5sum(APP, len(new)).lower() == md5(new)
            if verify_installed_rom:
                require(candidate_app and sha(stub.read_flash(APP, len(new))) == identity["candidate"],
                        "Offline display differs from the previously verified installed application.")
            require(original_app or candidate_app or (mode == "restore" and interrupted),
                    "Unrecognized on-device application.")
            if saved is None or history is None:
                require(original_app and mode == "install", "A verified original app is required for a new backup.")
                current = stub.read_flash(APP, span)
                require(len(current) == span and current[:len(old)] == old, "Original app readback failed.")
                if saved is None:
                    saved = current
                    atomic_private(backup, current)
                require(private_bytes(backup) == current, "Saved application differs from this unit.")
                record("prepared")
            target = new if mode == "install" else saved
            if stub.flash_md5sum(APP, len(target)).lower() != md5(target):
                attached()
                record("writing" if mode == "install" else "restoring")
                started = True
                write_app(stub, target, span)
            require(stub.read_flash(APP, len(target)) == target, "Full application readback differs.")
        version = probe(port, binding)
        require(version == 1, "Running application identification differs.")
        record("installed" if mode == "install" else "restored")
    except BaseException:
        if mode == "install" and started:
            attached()
            verify_guard()
            record("restoring")
            with loader(port, binding) as stub:
                check_layout(stub, table)
                write_app(stub, saved, span)
                require(stub.read_flash(APP, span) == saved, "Recovery readback differs.")
            require(probe(port, binding) == 1, "Recovered app identification differs.")
            record("restored")
        raise
    finally:
        if was_active:
            service("start")
    print("Application and calibrated paired display verified.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("install", "restore"))
    args = parser.parse_args()
    os.umask(0o077)
    require(os.getuid() != 0, "Run as the enrolled desktop owner.")
    import esptool
    require(esptool.__version__ == "4.9.0", "Use esptool 4.9.0.")
    sys.path.insert(0, str(Path.home() / ".local/share/orange-pi-wired-desktop/current"))
    from paired_system import private_file
    binding = private_file(Path.home() / ".config/orange-pi-wired-desktop/screen.mac", 6)
    state = Path.home() / ".local/state/paired-display-native-telemetry1"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = state.lstat()
    require(state.resolve() == state and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077, "Recovery directory permissions differ.")
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        transaction(args.mode, state, binding)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
