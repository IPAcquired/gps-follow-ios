"""Local, foreground CORVON743V2 telemetry-profile maintenance."""
import argparse
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import time


class MaintenanceError(Exception):
    pass


RATES = {"EXT_STAT": 2, "POSITION": 5, "EXTRA1": 10, "EXTRA3": 2, "RC_CHAN": 5, "RAW_SENS": 5}
PROTOCOLS = [2, 2, 42, 5, 2]
TARGETS = {f"MAV3_{suffix}": rate for suffix, rate in RATES.items()}
TARGETS["SERIAL4_BAUD"] = 115
STATUS_FILE = Path("/run/orangepi-mavlink/status.json")
PI_WORKER_PYTHON = "/opt/drone/venv/bin/python"


def monitor(path=STATUS_FILE, now=None):
    """Read one existing Pi publication. Never open a serial endpoint."""
    now = time.time() if now is None else now
    if not path.is_file():
        raise MaintenanceError("The monitor has no regular status file.")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise MaintenanceError("The monitor status must be a regular file.")
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise MaintenanceError("The status publication exceeds the size limit.")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise MaintenanceError("Unknown Pi monitor status schema.")
    ages = []
    for key in ("updated_unix", "heartbeat_updated_unix"):
        stamp = data.get(key)
        ages.append(round(now - stamp, 3) if type(stamp) in (float, int) and math.isfinite(stamp) else None)
    source = data.get("h743_source")
    expected = data.get("expected_source")
    source_matches = (isinstance(source, dict) and isinstance(expected, dict) and
                      type(source.get("system_id")) is int and 1 <= source["system_id"] <= 255 and
                      source.get("component_id") == 1 and source == expected)
    fresh = (all(age is not None and 0 <= age <= 2 for age in ages) and source_matches and
             data.get("transport") == "/dev/h743" and
             data.get("connected") is True and data.get("authority") == "read_only_no_mavlink_transmit")
    armed = data.get("armed")
    return {"fresh": fresh, "armed": armed if fresh and type(armed) is bool else None,
            "publication_age_seconds": ages[0], "heartbeat_age_seconds": ages[1]}


def parameter_snapshot(link):
    protocols = [link.read(f"SERIAL{i}_PROTOCOL")[0] for i in range(5)]
    if protocols != PROTOCOLS or link.read("SERIAL4_OPTIONS")[0] != 0:
        raise MaintenanceError("The serial layout does not match the MAV3 telemetry profile.")
    ports = [link.read("SERIAL_PASS1")[0], link.read("SERIAL_PASS2")[0]]
    if 4 in ports and all(port >= 0 for port in ports):
        raise MaintenanceError("Active serial passthrough includes UART4.")
    return {name: link.read(name) for name in TARGETS}


def save_journal(path, contents, create=False):
    """Reserve a new private journal, then atomically replace each durable revision."""
    if create:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as out:
            temp_name = out.name
            json.dump(contents, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_name, path)
        temp_name = None
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


def read_journal(path, device):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise MaintenanceError("Expected a small, local recovery journal.")
    data = path.read_bytes()
    item = json.loads(data)
    if not isinstance(item, dict) or item.get("version") != 1 or item.get("device") != device:
        raise MaintenanceError("Recovery journal belongs to a different device or format.")
    original, touched = item.get("original"), item.get("touched")
    if not isinstance(original, dict) or set(original) != set(TARGETS) or not isinstance(touched, list):
        raise MaintenanceError("Invalid recovery journal profile.")
    if any(type(n) is not str or n not in TARGETS for n in touched) or len(touched) != len(set(touched)):
        raise MaintenanceError("Invalid recovery journal change list.")
    for pair in original.values():
        if (not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int or
                not -(2**31) <= pair[0] < 2**31 or type(pair[1]) is not int or pair[1] not in (2, 4, 6)):
            raise MaintenanceError("Invalid original parameter value or type.")
    return item, hashlib.sha256(data).hexdigest()


def _undo(link, path, expected_digest=None):
    device = link.identity()
    snapshot = parameter_snapshot(link)
    item, digest = read_journal(path, device)
    if expected_digest is not None and not secrets.compare_digest(expected_digest, digest):
        raise MaintenanceError("Recovery journal changed since approval.")
    for name in reversed(item["touched"][:]):
        before, ptype = item["original"][name]
        link.ground_guard(device)
        current = link.read(name)
        if current[1] != ptype or current[0] not in (before, TARGETS[name]):
            raise MaintenanceError(f"{name} changed independently. Recovery stopped.")
        if current[0] != before:
            link.write(name, before, ptype)
        if link.read(name) != (before, ptype):
            raise MaintenanceError(f"{name} rollback readback failed.")
        item["touched"].remove(name)
        save_journal(path, item)
    return {"verified_rollback": True, "profile_parameters_read": len(snapshot)}


def _apply_profile(link, device, snapshot, journal):
    link.ground_guard(device)
    changes = [name for name, pair in snapshot.items() if pair[0] != TARGETS[name]]
    if not changes:
        return {"changed": [], "verified": True}
    item = {"version": 1, "device": device, "original": snapshot, "touched": []}
    save_journal(journal, item, create=True)
    try:
        for name in changes:
            link.ground_guard(device)
            if link.read(name) != snapshot[name]:
                raise MaintenanceError(f"{name} changed since the plan.")
            item["touched"].append(name)
            save_journal(journal, item)
            link.write(name, TARGETS[name], snapshot[name][1])
            if link.read(name) != (TARGETS[name], snapshot[name][1]):
                raise MaintenanceError(f"{name} readback failed.")
        link.ground_guard(device)
        after = parameter_snapshot(link)
        if any(after[k] != (v, snapshot[k][1]) for k, v in TARGETS.items()):
            raise MaintenanceError("Final profile verification failed.")
    except (Exception, KeyboardInterrupt) as exc:
        try:
            _undo(link, journal)
        except (Exception, KeyboardInterrupt) as recovery:
            raise MaintenanceError(f"Update interrupted. Recovery incomplete: {recovery}. Keep the journal.") from exc
        raise MaintenanceError(f"Update interrupted: {exc}. Attempted changes were rolled back and verified.") from exc
    return {"changed": changes, "verified": True}


PROPOSAL_TTL = 900


def operation_state(link, route, operation, journal):
    if route not in ("usb", "pi-uart0") or operation not in ("apply", "undo"):
        raise MaintenanceError("Unknown route or operation.")
    device = link.identity()
    snapshot = parameter_snapshot(link)
    if operation == "undo":
        record, undo_digest = read_journal(journal, device)
        targets = {name: record["original"][name][0] for name in record["touched"]}
        for name, value in targets.items():
            if snapshot[name][1] != record["original"][name][1] or snapshot[name][0] not in (TARGETS[name], value):
                raise MaintenanceError(f"{name} has changed independently since the update.")
    else:
        undo_digest = None
        targets = dict(TARGETS)
    if route == "pi-uart0" and (snapshot["SERIAL4_BAUD"][0] != 115 or targets.get("SERIAL4_BAUD", 115) != 115):
        raise MaintenanceError("Use a separate USB link to change the baud rate of the active maintenance UART.")
    return {"schema": 1, "operation": operation, "route": route, "device": device, "board_id": 1229,
            "firmware": "4.7.3", "protocols": PROTOCOLS, "stream_group": "MAV3",
            "before": {k: list(v) for k, v in snapshot.items()}, "targets": targets, "undo_record": undo_digest}


def describe(state):
    return {k: {"from": state["before"][k][0], "to": v} for k, v in state["targets"].items()
            if state["before"][k][0] != v}


def prepare(link, route, operation, path, journal=None):
    state = operation_state(link, route, operation, journal)
    created = int(time.time())
    state.update(created=created, expires=created + PROPOSAL_TTL, nonce=secrets.token_hex(16),
                 file_binding=hashlib.sha256(os.fsencode(path.resolve())).hexdigest())
    save_journal(path, state, create=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"operation": operation, "route": route, "changes": describe(state), "expires_unix": state["expires"],
            "approval_sha256": digest, "on_failure": "restore attempted settings when the same board is grounded"}


def reviewed_proposal(path, digest, route, operation):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise MaintenanceError("Expected a regular local proposal file.")
    data = path.read_bytes()
    if (not isinstance(digest, str) or len(digest) != 64 or not digest.isascii() or
            not secrets.compare_digest(hashlib.sha256(data).hexdigest(), digest.lower())):
        raise MaintenanceError("The approval digest does not match the exact proposal.")
    state = json.loads(data)
    if not isinstance(state, dict) or state.get("operation") != operation or state.get("route") != route:
        raise MaintenanceError("The proposal has a different route or operation.")
    if state.get("file_binding") != hashlib.sha256(os.fsencode(path.resolve())).hexdigest():
        raise MaintenanceError("Use the original local proposal file.")
    created, expires = state.get("created"), state.get("expires")
    if not (type(created) is int and type(expires) is int and expires - created == PROPOSAL_TTL
            and created <= time.time() < expires):
        raise MaintenanceError("The proposal has expired or its timestamps are invalid.")
    return state


def execute_approved(link, route, operation, path, digest, journal):
    original = reviewed_proposal(path, digest, route, operation)
    current = operation_state(link, route, operation, journal)
    if current != {k: v for k, v in original.items() if k not in ("created", "expires", "nonce", "file_binding")}:
        raise MaintenanceError("Controller, profile, recovery record or pre-state changed; prepare a new proposal.")
    if operation == "apply" and describe(current) and journal.exists():
        raise MaintenanceError("The rollback journal already exists; choose a new private file.")
    link.ground_guard(current["device"])
    reviewed_proposal(path, digest, route, operation)
    # All proposal copies in this private directory share the nonce-based consumed marker.
    nonce = original.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
        raise MaintenanceError("Invalid proposal identifier.")
    used = path.parent / (".corvon-consumed-" + nonce)
    try:
        save_journal(used, {"approved": digest}, create=True)
    except FileExistsError as exc:
        raise MaintenanceError("This proposal was already used.") from exc
    if operation == "undo":
        return _undo(link, journal, current["undo_record"])
    snapshot = {name: tuple(pair) for name, pair in current["before"].items()}
    return _apply_profile(link, current["device"], snapshot, journal)


class SerialLink:
    """Direct local serial only, with guarded access to the shared Pi native UART."""
    def __init__(self, route, port=None):
        from pymavlink import mavutil
        if route == "pi-uart0" and port is None:
            from uart_handoff import verify_worker_port
            device = verify_worker_port()
        elif route == "usb" and port:
            from serial.tools import list_ports
            selected = os.path.normcase(os.path.realpath(port))
            matches = [p for p in list_ports.comports()
                       if os.path.normcase(os.path.realpath(p.device)) == selected
                       and (p.vid, p.pid) == (0x1209, 0x5741)]
            if len(matches) != 1:
                raise MaintenanceError("Select a directly attached ArduPilot USB serial device.")
            device = matches[0].device
        else:
            raise MaintenanceError("Unknown serial route or port selection.")
        self.bus = mavutil.mavlink_connection(device, baud=115200, autoreconnect=False,
                                              source_system=255, source_component=191)
        if os.name == "posix":
            try:
                self.bus.port.exclusive = True
                if route == "pi-uart0":
                    import fcntl
                    import termios
                    fcntl.ioctl(self.bus.port.fileno(), termios.TIOCEXCL)
                    verify_worker_port()
            except BaseException:
                self.bus.close()
                raise
        self.target = None
        self.guard_active = False

    def close(self):
        self.bus.close()

    def wait(self, msg_type, test=lambda message: True, timeout=4):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            msg = self.bus.recv_match(blocking=True, timeout=min(0.25, max(0, until - time.monotonic())))
            if msg is None:
                continue
            source = (msg.get_srcSystem(), msg.get_srcComponent())
            if self.target and source != self.target:
                continue
            if self.guard_active and msg.get_type() == "HEARTBEAT" and msg.base_mode & 128:
                raise MaintenanceError("Controller is armed.")
            if self.guard_active and msg.get_type() == "EXTENDED_SYS_STATE" and msg.landed_state != 1:
                raise MaintenanceError("Controller is not reporting on-ground.")
            if msg.get_type() == msg_type and test(msg):
                return msg
        raise MaintenanceError(f"No matching {msg_type} reply.")

    def request_message(self, message_id):
        self.bus.mav.command_long_send(*self.target, 512, 0, message_id, 0, 0, 0, 0, 0, 0)

    def drain(self):
        for _ in range(4096):
            if self.bus.recv_match(blocking=False) is None:
                return
        raise MaintenanceError("The maintenance link has a persistent input backlog.")

    def identity(self):
        self.drain()
        hb = self.wait("HEARTBEAT", lambda m: m.autopilot == 3 and m.get_srcComponent() == 1)
        self.target = (hb.get_srcSystem(), hb.get_srcComponent())
        self.request_message(148)
        v = self.wait("AUTOPILOT_VERSION")
        if v.board_version >> 16 != 1229 or v.flight_sw_version >> 8 != 0x040703:
            raise MaintenanceError("Expected CORVON743V2 running ArduCopter 4.7.3.")
        # MAV_TYPE values for ArduCopter multicopters and helicopters.
        if hb.type not in (2, 3, 4, 13, 14, 15, 29, 35, 43):
            raise MaintenanceError("Expected a Copter heartbeat.")
        uid = int(getattr(v, "uid", 0)).to_bytes(8, "little")
        if not any(uid):
            uid = bytes(getattr(v, "uid2", b""))
        if not any(uid):
            raise MaintenanceError("Missing hardware identity for device-bound recovery.")
        return hashlib.sha256(b"CORVON743V2\0" + uid).hexdigest()

    def ground_guard(self, device):
        self.guard_active = True
        if self.identity() != device:
            raise MaintenanceError("Controller changed during maintenance.")
        self.request_message(245)
        self.wait("EXTENDED_SYS_STATE", lambda m: m.landed_state == 1)

    def read(self, name):
        self.bus.mav.param_request_read_send(*self.target, name.encode("ascii"), -1)
        msg = self.wait("PARAM_VALUE", lambda m: m.param_id == name)
        if msg.param_type not in (2, 4, 6) or not math.isfinite(msg.param_value) or not msg.param_value.is_integer():
            raise MaintenanceError(f"Unexpected type or value for {name}.")
        return int(msg.param_value), msg.param_type

    def write(self, name, value, ptype):
        if name not in TARGETS or not self.guard_active:
            raise MaintenanceError("Denied parameter write outside the guarded profile.")
        self.bus.mav.param_set_send(*self.target, name.encode("ascii"), value, ptype)
        msg = self.wait("PARAM_VALUE", lambda m: m.param_id == name)
        if msg.param_value != value or msg.param_type != ptype:
            raise MaintenanceError(f"{name} acknowledgement mismatch.")


FIRMWARE_ACTIONS = ("firmware-prepare", "firmware-apply", "firmware-verify", "firmware-cleanup")


def check_install(bundle):
    """Check the pinned bundle and installed adapters without opening a device or contacting systemd."""
    from corvon_firmware import load_package, FirmwareError
    issues = []
    try:
        package, app = load_package(bundle)
        package_ok = bool(package and app)
    except (FirmwareError, OSError, ValueError) as error:
        package_ok = False
        issues.append(str(error))
    try:
        from pymavlink import mavftp, mavutil
        from serial import Serial
        from serial.tools import list_ports
        if not callable(mavutil.mavlink_connection) or not callable(list_ports.comports):
            raise ValueError("serial MAVLink adapter unavailable")
        if os.name == "posix" and not hasattr(Serial, "exclusive"):
            raise ValueError("pyserial lacks exclusive access")
        ftp = mavftp.MAVFTP
        inspect.signature(ftp).bind(object(), 1, 1)
        inspect.signature(ftp.read).bind(None, "file", 100, 0)
        inspect.signature(ftp.cmd_put).bind(None, ["src", "/dest"], fh=object())
        inspect.signature(ftp.process_ftp_reply).bind(None, "put", timeout=100)
        for method in ("cmd_list", "cmd_rename", "cmd_rm"):
            inspect.signature(getattr(ftp, method)).bind(None, ["name"])
    except (ImportError, AttributeError, TypeError, ValueError) as error:
        issues.append(f"Runtime dependency: {error}")
    return {"ready": not issues and package_ok, "firmware_bundle_verified": package_ok, "issues": issues}


def firmware_command(args):
    """Dispatch only the installed, named adapter, never code from a bundle or transaction."""
    action = args.action.removeprefix("firmware-")
    approval = getattr(args, "approve", None)
    if args.action not in FIRMWARE_ACTIONS or args.route != "pi-uart0":
        raise MaintenanceError("Unknown firmware action or route.")
    if action in ("apply", "cleanup"):
        if not isinstance(approval, str) or len(approval) != 64 or any(c not in "0123456789abcdef" for c in approval.lower()):
            raise MaintenanceError("Firmware write operations require the reviewed SHA-256 digest.")
    elif approval is not None:
        raise MaintenanceError("Read-only firmware operations do not consume approvals.")
    bundle = args.bundle_dir.absolute()
    transaction = args.transaction_dir.absolute()
    if not bundle.is_dir():
        raise MaintenanceError("Select the reviewed firmware bundle directory.")
    if not args.worker:
        from uart_handoff import handoff
        worker = [PI_WORKER_PYTHON, str(Path(__file__).resolve()), args.action,
                  "--worker", "--route", "pi-uart0", "--bundle-dir", str(bundle), "--transaction-dir", str(transaction)]
        if approval:
            worker.extend(["--approve", approval])
        return handoff(worker)
    from corvon_firmware import FirmwareError, run_firmware
    link = SerialLink("pi-uart0")
    try:
        result = run_firmware(link, action, bundle, transaction, approval=approval)
    except FirmwareError as failure:
        raise MaintenanceError(str(failure)) from failure
    finally:
        link.close()
    if action == "prepare" and "proposal" in result:
        record = result["proposal"]
        result = {"approval_sha256": result["approval_sha256"],
                  "proposal": {key: record[key] for key in ("board_id", "version", "package_sha256", "application_sha256",
                                                            "expires", "trigger", "activation", "cleanup")},
                  "effect": "Stage the pinned firmware on the controller SD card for the owner's cold power cycle."}
    print(json.dumps(result, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    check = commands.add_parser("check", help="verify dependencies and the local firmware package")
    check.add_argument("--bundle-dir", type=Path, default=Path(__file__).resolve().parent)
    passive = commands.add_parser("monitor", help="read the existing passive monitor's status")
    passive.add_argument("--status-file", type=Path, default=STATUS_FILE)
    review = commands.add_parser("review", help="inspect a local proposal without opening a port")
    review.add_argument("--proposal", type=Path, required=True)
    for name in FIRMWARE_ACTIONS:
        cmd = commands.add_parser(name)
        cmd.add_argument("--route", choices=("pi-uart0",), required=True)
        cmd.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        cmd.add_argument("--bundle-dir", type=Path, required=True)
        cmd.add_argument("--transaction-dir", type=Path, required=True)
        if name in ("firmware-apply", "firmware-cleanup"):
            cmd.add_argument("--approve", required=True, help="exact reviewed firmware decision SHA-256")
    for action in ("audit", "plan", "plan-undo", "apply", "undo"):
        cmd = commands.add_parser(action)
        cmd.add_argument("--route", choices=("pi-uart0", "usb"), required=True)
        cmd.add_argument("--port", help="USB serial device; omit for the managed Pi UART")
        cmd.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
        if action != "audit":
            cmd.add_argument("--proposal", type=Path, required=True)
        if action in ("plan-undo", "apply", "undo"):
            cmd.add_argument("--journal", type=Path, required=True)
        if action in ("apply", "undo"):
            cmd.add_argument("--approve", required=True, help="reviewed proposal SHA-256")
    args = parser.parse_args()
    if args.action == "check":
        result = check_install(args.bundle_dir)
        print(json.dumps(result, indent=2))
        return 0 if result["ready"] else 1
    if args.action in FIRMWARE_ACTIONS:
        return firmware_command(args)
    if args.action == "monitor":
        result = monitor(args.status_file)
    elif args.action == "review":
        if args.proposal.is_symlink() or not args.proposal.is_file() or args.proposal.stat().st_size > 8192:
            raise MaintenanceError("Expected a regular local proposal file.")
        raw = args.proposal.read_bytes()
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise MaintenanceError("Invalid proposal record.")
        digest = hashlib.sha256(raw).hexdigest()
        reviewed_proposal(args.proposal, digest, record.get("route"), record.get("operation"))
        result = {"approval_sha256": digest, "route": record["route"], "operation": record["operation"],
                  "expires_unix": record["expires"], "changes": describe(record), "targets": record["targets"]}
    else:
        if (args.route == "usb") != bool(args.port) or (args.worker and args.route != "pi-uart0"):
            parser.error("Select a USB device with --port, or omit --port for pi-uart0.")
        operation = "undo" if args.action in ("plan-undo", "undo") else "apply"
        proposal = args.proposal.absolute() if getattr(args, "proposal", None) else None
        journal = args.journal.absolute() if getattr(args, "journal", None) else None
        if args.action in ("apply", "undo"):
            reviewed_proposal(proposal, args.approve, args.route, operation)
        if args.action.startswith("plan") and proposal.exists():
            raise MaintenanceError("Choose a new local proposal file.")
        if args.route == "pi-uart0" and not args.worker:
            from uart_handoff import handoff
            worker = [PI_WORKER_PYTHON, str(Path(__file__).resolve()), args.action,
                      "--worker", "--route", args.route]
            for flag, value in (("--proposal", proposal), ("--journal", journal), ("--approve", getattr(args, "approve", None))):
                if value is not None:
                    worker.extend([flag, str(value)])
            return handoff(worker)
        link = SerialLink(args.route, args.port)
        try:
            if args.action == "audit":
                state = operation_state(link, args.route, operation, journal)
                result = {"board_id": 1229, "stream_group": "MAV3", "changes": describe(state)}
            elif args.action.startswith("plan"):
                result = prepare(link, args.route, operation, proposal, journal)
            else:
                result = execute_approved(link, args.route, operation, proposal, args.approve, journal)
        finally:
            link.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    # The handoff module imports this public name for the shared error and monitor types.
    sys.modules.setdefault("companion_maintenance", sys.modules[__name__])
    try:
        sys.exit(main())
    except subprocess.SubprocessError:
        print("Maintenance stopped: the system service manager did not complete the handoff.", file=sys.stderr)
        sys.exit(1)
    except (MaintenanceError, OSError, ValueError, ImportError) as error:
        print(f"Maintenance stopped: {error}", file=sys.stderr)
        sys.exit(1)
