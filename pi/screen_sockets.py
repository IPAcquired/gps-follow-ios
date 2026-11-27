"""Approve an additional physical USB socket for the already enrolled touchscreen."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import time

SOCKET = re.compile(r"[0-9]+-[0-9]+(?:\.[0-9]+)*")
EXTRA = "additional-screen-sockets.json"


def extra_sockets(profile):
    from paired_system import private_file
    try:
        values = json.loads(private_file(profile / EXTRA, 1024))
    except FileNotFoundError:
        return []
    if (not isinstance(values, list) or len(values) > 16
            or any(not isinstance(v, str) or not SOCKET.fullmatch(v) for v in values)
            or len(set(values)) != len(values)):
        raise ValueError("Invalid owner-approved socket list.")
    return values


def approved_sockets(primary):
    from paired_system import private_file
    try:
        original = private_file(primary, 64).decode("ascii").strip()
    except (OSError, ValueError):
        return ()
    if not SOCKET.fullmatch(original):
        return ()
    try:
        extra = extra_sockets(primary.parent)
    except (OSError, ValueError):
        extra = []
    return (original, *extra)


def port_location(port):
    node = Path(port).resolve(strict=True)
    if node.parent != Path("/dev") or not re.fullmatch(r"ttyUSB[0-9]+", node.name):
        raise ValueError("Select the USB serial device for the screen.")
    leaf = (Path("/sys/class/tty") / node.name / "device").resolve(strict=True)
    parent = next((p for p in (leaf, *leaf.parents) if (p/"idVendor").is_file()), None)
    if (parent is None or not SOCKET.fullmatch(parent.name)
            or (parent/"idVendor").read_text().strip() != "1a86"
            or (parent/"idProduct").read_text().strip() != "7523"):
        raise ValueError("The selected socket does not contain the screen's CH340 USB interface.")
    return str(node), parent.name, (parent/"devnum").read_text().strip()


def prove_screen(node, profile):
    from direct_usb import open_direct
    from paired_system import enrollment, private_file
    from paired_wire import authenticate, wait_for_screen
    mac = private_file(profile/"screen.mac", 6)
    key = enrollment()
    deadline = time.monotonic()+22
    def check_deadline():
        if time.monotonic() >= deadline:
            raise TimeoutError("Open Pi > Wired Desktop on the enrolled screen and retry.")
    with open_direct(node, mac, check_deadline) as wire:
        wire.begin()
        try:
            wait_for_screen(wire, secrets.randbelow(2**31-1)+1)
            session = authenticate(wire, key)
            if not session.channel.ready:
                raise PermissionError("The screen did not prove its existing pairing.")
        finally:
            wire.end()


def approve(primary, port):
    from paired_system import atomic_json, private_dir
    profile = private_dir(primary.parent)
    fd = os.open(profile/".pair-lock", os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        approved = approved_sockets(primary)
        if not approved:
            raise ValueError("Commission the touchscreen on its primary socket first.")
        node, location, connection = port_location(port)
        if location in approved:
            return False
        extras = extra_sockets(profile)
        if len(extras) >= 16:
            raise ValueError("The socket list is full.")
        prove_screen(node, profile)
        if port_location(port) != (node, location, connection):
            raise RuntimeError("The USB attachment changed during verification.")
        atomic_json(profile/EXTRA, [*extras, location])
        if location not in approved_sockets(primary):
            raise OSError("Could not verify the saved socket.")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Attached screen, for example /dev/ttyUSB0")
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.exit(2, "Run this as the existing desktop owner.\n")
    try:
        changed = approve(Path.home()/".config/orange-pi-wired-desktop/direct-topology", args.port)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error)+"\n")
    print("Paired screen proved on this socket; approval saved." if changed else "Socket already approved.")
