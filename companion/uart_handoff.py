"""Temporary, systemd-supervised handoff of the approved Orange Pi native UART."""

import base64
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import socket
import time

from companion_maintenance import MaintenanceError, monitor

MONITOR = "orangepi-mavlink-monitor.service"
WORKER = "orangepi-reviewed-uart.service"
TTY = "/dev/ttyS0"
ALIAS = "/dev/h743"
SYSTEMCTL = "/usr/bin/systemctl"
RUN = "/usr/bin/systemd-run"
LIMIT = 150
FIRMWARE_LIMIT = 2400
FIRMWARE_ACTIONS = {"firmware-prepare", "firmware-apply", "firmware-verify", "firmware-cleanup"}
WORKER_PYTHON = "/opt/drone/venv/bin/python"
LOCK = "/run/lock/orangepi-reviewed-uart.lock"
TOOLS = Path(__file__).resolve().parent

# Executed by systemd's root pre-start hook using isolated system Python.
# No user-supplied value, user module, file content or command is evaluated.
ROOT_CHECK = """import os, pathlib, stat, subprocess, sys
tty = pathlib.Path('/dev/ttyS0')
if pathlib.Path('/dev/h743').resolve(strict=True) != tty:
    sys.exit('Native UART alias changed.')
node = tty.stat()
if not stat.S_ISCHR(node.st_mode):
    sys.exit('Native UART is not a character device.')
allowed = None
if sys.argv[1] == 'claimed':
    allowed = subprocess.check_output(['/usr/bin/systemctl','--system','show','--value','--property=MainPID','orangepi-reviewed-uart.service'],text=True,timeout=3).strip()
    if not allowed.isdecimal() or int(allowed) < 2:
        sys.exit('Missing system worker PID.')
saw_owner = False
for process in pathlib.Path('/proc').iterdir():
    if not process.name.isdecimal():
        continue
    try:
        for descriptor in (process / 'fd').iterdir():
            try:
                current = descriptor.stat()
            except FileNotFoundError:
                continue
            if stat.S_ISCHR(current.st_mode) and current.st_rdev == node.st_rdev:
                if process.name != allowed:
                    sys.exit('Another process holds the native UART.')
                saw_owner = True
    except (FileNotFoundError, ProcessLookupError):
        continue
if allowed is not None and not saw_owner:
    sys.exit('The worker did not claim the native UART.')
"""


def _unit(name, properties):
    output = subprocess.run(
        [SYSTEMCTL, "--system", "--no-ask-password", "show", name,
         "--property=" + ",".join(properties)],
        text=True, capture_output=True, timeout=6,
    )
    result = dict(line.split("=", 1) for line in output.stdout.splitlines() if "=" in line)
    if output.returncode and result.get("LoadState") != "not-found":
        raise MaintenanceError("Could not verify the system service state.")
    if not result or not set(properties).issubset(result):
        raise MaintenanceError("Incomplete system service state.")
    return result


def _owner():
    data = _unit(MONITOR, ("LoadState", "ActiveState", "User", "FragmentPath", "ExecStart"))
    fragments = {f"{d}/{MONITOR}" for d in ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system")}
    if (data["LoadState"] != "loaded" or data["FragmentPath"] not in fragments
            or data["User"] != "drone" or "/usr/local/bin/orangepi-mavlink-monitor" not in data["ExecStart"]):
        raise MaintenanceError("The installed native monitoring service could not be identified.")
    return data["ActiveState"]


def _healthy(since=None):
    observed = time.time()
    sample = monitor(now=observed)
    if sample.get("fresh") is not True or sample.get("armed") is not False:
        return False
    return since is None or all(observed - sample[key] > since + 0.002
                                for key in ("publication_age_seconds", "heartbeat_age_seconds"))


def _call(action, name):
    subprocess.run([SYSTEMCTL, "--system", "--no-ask-password", action, name],
                   check=True, timeout=15)


def _restore(description):
    since = time.time()
    current = _unit(WORKER, ("LoadState", "ActiveState", "Description"))
    if current["LoadState"] != "not-found" and current["ActiveState"] not in ("inactive", "failed"):
        if current["Description"] != description:
            raise MaintenanceError("Another handoff owns the UART. Its service was left alone.")
        _call("stop", WORKER)
    if _owner() != "active":
        _call("start", MONITOR)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if _owner() == "active" and _healthy(since):
                return
        except (OSError, ValueError, MaintenanceError):
            pass
        time.sleep(0.5)
    raise MaintenanceError("Monitor restoration did not produce fresh disarmed native-UART telemetry.")


@contextlib.contextmanager
def _lease():
    import fcntl
    fd = os.open(LOCK, os.O_NOFOLLOW | os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        status = os.fstat(fd)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_uid != os.geteuid() or status.st_mode & 0o077:
            raise MaintenanceError("The maintenance lock must be private and owned by the manager.")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MaintenanceError("Another maintenance session owns the UART.") from exc
        yield
    finally:
        os.close(fd)


def _validate(argv):
    if not isinstance(argv, (list, tuple)) or len(argv) < 6 or not all(isinstance(x, str) for x in argv):
        raise MaintenanceError("Invalid worker request.")
    if (argv[0] != WORKER_PYTHON
            or argv[1] != str(TOOLS / "companion_maintenance.py")
            or argv[2] not in {"audit", "plan", "plan-undo", "apply", "undo"} | FIRMWARE_ACTIONS
            or list(argv[3:6]) != ["--worker", "--route", "pi-uart0"]):
        raise MaintenanceError("Only the local reviewed telemetry worker may request the UART.")
    if len(argv[6:]) % 2:
        raise MaintenanceError("Malformed worker options.")
    seen = set()
    firmware = argv[2] in FIRMWARE_ACTIONS
    allowed = {"--bundle-dir", "--transaction-dir"} if firmware else {"--proposal", "--journal"}
    if argv[2] in {"apply", "undo", "firmware-apply", "firmware-cleanup"}:
        allowed.add("--approve")
    for option, value in zip(argv[6::2], argv[7::2]):
        if option not in allowed or option in seen:
            raise MaintenanceError("Unsupported or repeated worker option.")
        if option != "--approve" and not Path(value).is_absolute():
            raise MaintenanceError("Local files must have absolute paths.")
        if option == "--approve" and not re.fullmatch(r"[0-9a-f]{64}", value):
            raise MaintenanceError("Approval must be the exact proposal digest.")
        seen.add(option)
    if firmware and seen != allowed:
        raise MaintenanceError("The firmware worker requires its exact operation arguments.")


def handoff(argv):
    """Run only the designated worker, restoring passive monitoring on every exit."""
    _validate(argv)
    description = "Reviewed native UART maintenance " + secrets.token_hex(16)
    with _lease():
        current = _unit(WORKER, ("LoadState", "ActiveState"))
        if current["LoadState"] != "not-found":
            raise MaintenanceError("The reserved worker unit already exists.")
        if _owner() != "active" or not _healthy():
            raise MaintenanceError("The native UART monitor must show fresh disarmed telemetry.")
        limit = FIRMWARE_LIMIT if argv[2] in FIRMWARE_ACTIONS else LIMIT
        # A single-line fixed program avoids different escaping rules in
        # systemd versions. Only this built-in constant is encoded.
        payload = base64.b64encode(ROOT_CHECK.encode("ascii")).decode("ascii")
        checker = "+/usr/bin/python3 -I -c " + json.dumps("import base64;exec(base64.b64decode('" + payload + "'))")
        settings = [
            "Description=" + description,
            "User=drone", "Group=drone", "SupplementaryGroups=dialout",
            "After=" + MONITOR, "Conflicts=" + MONITOR,
            "NoNewPrivileges=yes", "UMask=0077", "KillMode=control-group",
            f"RuntimeMaxSec={limit}", "TimeoutStartSec=30", "TimeoutStopSec=8", "NotifyAccess=main",
            "ExecStartPre=" + checker + " idle", "ExecStartPost=" + checker + " claimed",
            "ExecStopPost=+" + SYSTEMCTL + " --system --no-ask-password --no-block start " + MONITOR,
        ]
        command = [RUN, "--system", "--no-ask-password", "--quiet", "--wait", "--pipe",
                   "--collect", "--service-type=notify", "--unit=" + WORKER]
        command.extend("--property=" + setting for setting in settings)
        try:
            run = subprocess.run([*command, "--", *argv], timeout=limit + 55)
            return run.returncode
        finally:
            _restore(description)


def verify_worker_port():
    """Permit opening this UART only from the unprivileged transient worker itself."""
    import pwd
    if os.geteuid() != pwd.getpwnam("drone").pw_uid:
        raise MaintenanceError("The UART worker must run as the companion user.")
    group = "/system.slice/" + WORKER
    groups = Path("/proc/self/cgroup").read_text().splitlines()
    if ("0::" + group) not in groups:
        raise MaintenanceError("The native UART requires the supervised system worker.")
    details = _unit(WORKER, ("Transient", "ControlGroup", "ActiveState", "MainPID", "User"))
    if (details["Transient"] != "yes" or details["ControlGroup"] != group
            or details["ActiveState"] not in ("active", "activating") or details["MainPID"] != str(os.getpid())
            or details["User"] != "drone" or _owner() != "inactive"):
        raise MaintenanceError("The monitored UART has not been handed to this worker.")
    path = Path(ALIAS).resolve(strict=True)
    if str(path) != TTY or not stat.S_ISCHR(path.stat().st_mode):
        raise MaintenanceError("The native UART alias does not match the expected tty.")
    node = path.stat()
    for entry in Path("/proc/self/fd").iterdir():
        try:
            held = os.fstat(int(entry.name))
        except OSError:
            continue
        if stat.S_ISCHR(held.st_mode) and held.st_rdev == node.st_rdev:
            _confirm_claim(int(entry.name))
            break
    return TTY


def _confirm_claim(fd):
    import array
    import fcntl
    import termios
    exclusive = array.array("i", [0])
    fcntl.ioctl(fd, getattr(termios, "TIOCGEXCL", 0x80045440), exclusive, True)
    if exclusive[0] != 1:
        raise MaintenanceError("The UART file descriptor lacks a kernel-exclusive claim.")
    endpoint = os.environ.get("NOTIFY_SOCKET")
    if not endpoint or not (endpoint.startswith("/run/systemd/") or endpoint.startswith("@/org/freedesktop/systemd")):
        raise MaintenanceError("The system service readiness channel is missing.")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.sendto(b"READY=1", "\x00" + endpoint[1:] if endpoint.startswith("@") else endpoint)
    # A root ExecStartPost scans every PID after TIOCEXCL. systemd will mark
    # us active only after this independent check. No serial requests precede it.
    until = time.monotonic() + 10
    while time.monotonic() < until:
        state = _unit(WORKER, ("LoadState", "ActiveState", "MainPID"))
        if state["MainPID"] != str(os.getpid()) or state["ActiveState"] not in ("active","activating"):
            break
        if state["ActiveState"] == "active":
            return
        time.sleep(0.1)
    raise MaintenanceError("The system manager did not verify sole UART ownership.")
