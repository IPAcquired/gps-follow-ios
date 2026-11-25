"""Owner-invoked SD bootloader transactions for one reviewed CORVON743V2 package."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import time


BOARD = 1229
VERSION = 0x040703FF
BASE = 0x20000
END = 0x1C0000
FLASH = 0x200000
CHUNK = 65536
FILENAME = "CORVON743V2-4.7.3-R2.abin"
PACKAGE_HASH = "9bbb2a3778e4fba3e4be54c9b3ebb8bea2730dcfb287d039b55da81fe9b204d2"
APP_HASH = "1d756c6c14388a0e641b044117aa0e14217b27f52f55e7edb79ee85abd57c1a6"
BOOT_HASH = "4b56249587234f36774e0859e32b58a19c48adda30ada481d8d3a540029f5e98"
COMPLETE = "ardupilot-flashed.abin"
TRIGGER = "ardupilot.abin"
RESERVED = {TRIGGER, COMPLETE, "ardupilot-verify.abin", "ardupilot-flash.abin"}
SETTINGS = ("FRAME_CLASS", "FRAME_TYPE", "SERIAL4_PROTOCOL", "SERIAL4_BAUD", "LOG_BACKEND_TYPE")


class FirmwareError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise FirmwareError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def load_package(directory):
    path = Path(directory) / FILENAME
    require(path.is_file() and path.stat().st_size == 1536143, "Expected the reviewed 4.7.3 R2 package.")
    package = path.read_bytes()
    require(sha(package) == PACKAGE_HASH, "Package does not match the installed release allowlist.")
    head, app = package.split(b"--\n", 1)
    require(len(app) == 1536048 and sha(app) == APP_HASH, "Application digest mismatch.")
    expected = b"git version: d9c5097c3d8333435712ffed86bca8ce00c4bb46\nMD5: "
    require(head == expected + hashlib.md5(app).hexdigest().encode() + b"\n", "Invalid ABIN header.")
    require(BASE + len(app) + (128 - len(app) % 128) <= END, "Padded image exceeds application flash.")
    return package, app


def save(path, value, create=False):
    mode = "xb" if create else "wb"
    dest = path if create else path.with_name("." + secrets.token_hex(12) + ".tmp")
    try:
        with dest.open(mode) as out:
            os.chmod(dest, 0o600)
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        if not create:
            os.replace(dest, path)
        if os.name == "posix":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if not create:
            dest.unlink(missing_ok=True)


class PeerBus:
    """Filter library FTP replies to the peer owning the current transaction."""
    def __init__(self, link):
        self.link = link
        self.source_system = link.bus.source_system
        self.source_component = link.bus.source_component
        self.mav = link.bus.mav

    def recv_match(self, type=None, blocking=False, timeout=None):
        wanted = {type} if isinstance(type, str) else set(type or ())
        limit = time.monotonic() + (timeout or 0)
        for _ in range(512):
            msg = self.link.bus.recv_match(blocking=blocking, timeout=max(0, limit - time.monotonic()))
            if msg is None:
                return None
            if (msg.get_srcSystem(), msg.get_srcComponent()) == self.link.target:
                kind = msg.get_type()
                if kind == "HEARTBEAT":
                    require(not msg.base_mode & 128, "The controller armed during firmware maintenance.")
                if kind == "EXTENDED_SYS_STATE":
                    require(msg.landed_state == 1, "The controller stopped reporting on-ground.")
                if not wanted or kind in wanted:
                    return msg
            if blocking and time.monotonic() >= limit:
                return None
        return None


class Board:
    """Use the already opened maintenance session. This class never opens a port."""
    def __init__(self, link):
        from pymavlink import mavftp
        self.link = link
        self.device = link.identity()
        self.guard(self.device)
        self.ftp = mavftp.MAVFTP(PeerBus(link), *link.target)

    def guard(self, expected):
        self.link.ground_guard(expected)
        hb = self.link.wait("HEARTBEAT")
        require(hb.system_status in (3, 4) and not hb.base_mode & 128, "Controller startup or health is incomplete.")
        return self.device

    def settings(self):
        return {name: self.link.read(name)[0] for name in SETTINGS}

    def health(self):
        self.link.request_message(1)
        status = self.link.wait("SYS_STATUS")
        require(all(value & 8 for value in (status.onboard_control_sensors_present,
                    status.onboard_control_sensors_enabled, status.onboard_control_sensors_health)),
                "The controller has not verified a healthy absolute-pressure sensor.")
        self.link.request_message(29)
        pressure = self.link.wait("SCALED_PRESSURE")
        require(math.isfinite(pressure.press_abs) and pressure.press_abs > 0,
                "No valid onboard barometer reading after restart.")

    def root(self):
        self.ok(self.ftp.cmd_list(["/"]), "List SD root")
        return {e.name.casefold(): (-1 if e.is_dir else e.size_b) for e in self.ftp.list_result}

    @staticmethod
    def ok(reply, action):
        require(reply.error_code == 0, f"{action} failed ({reply.error_code}, {reply.system_error}).")

    def read(self, name, size, offset=0):
        parts = []
        for start in range(0, size, CHUNK):
            count = min(size-start, CHUNK)
            part = self.ftp.read(name, count, offset+start)
            require(part is not None and len(part) == count, f"Short read from {name}.")
            parts.append(bytes(part))
        return b"".join(parts)

    def upload(self, name, contents):
        self.ok(self.ftp.cmd_put(["approved-firmware", "/" + name], fh=io.BytesIO(contents)), "Start SD upload")
        self.ok(self.ftp.process_ftp_reply("put", timeout=1000), "Finish SD upload")

    def promote(self, name):
        self.ok(self.ftp.cmd_rename(["/" + name, "/" + TRIGGER]), "Promote staged firmware")

    def remove(self, name):
        self.ok(self.ftp.cmd_rm(["/" + name]), "Remove verified transaction file")


def flash_snapshot(board):
    image = board.read("@SYS/flash.bin", FLASH)
    require(len(image) == FLASH and sha(image[:BASE]) == BOOT_HASH, "Installed bootloader identity changed.")
    return image


def proposal_digest(proposal):
    return sha(encoded(proposal))


def store_phase(folder, state):
    save(folder / "state.json", encoded({"phase": state}))


def summary(plan):
    return {"approval_sha256": proposal_digest(plan), "proposal": plan}


def prepare(board, folder, app, clock):
    require(not folder.exists(), "Use a new private transaction directory for a fresh plan.")
    board.guard(board.device)
    roots = board.root()
    require(not RESERVED.intersection(roots), "An existing SD bootloader trigger or result needs reconciliation.")
    before = flash_snapshot(board)
    if before[BASE:BASE+len(app)] == app:
        return {"status": "already-current", "application_sha256": APP_HASH}
    storage = board.read("@SYS/storage.bin", 32768)
    settings = board.settings()
    board.guard(board.device)
    folder.mkdir(mode=0o700, parents=False)
    save(folder / "flash-before.bin", before, create=True)
    save(folder / "parameters-before.bin", storage, create=True)
    nonce = secrets.token_hex(16)
    now = int(clock())
    plan = dict(schema=1, board_id=BOARD, board=board.device, version="4.7.3 R2", package_sha256=PACKAGE_HASH,
                application_sha256=APP_HASH, prior_flash_sha256=sha(before), parameter_backup_sha256=sha(storage),
                previous_region_sha256=sha(before[BASE:END]), settings=settings, created=now,
                expires=now+900, inert_name=f"fw-{nonce}.part", trigger="/"+TRIGGER,
                activation="owner cold power cycle", cleanup="verified flashed marker only")
    save(folder / "proposal.json", encoded(plan), create=True)
    store_phase(folder, "prepared")
    return summary(plan)


def read_plan(folder, board):
    st = folder.stat()
    require(not folder.is_symlink() and folder.is_dir(), "A private transaction directory is required.")
    if os.name == "posix":
        require(st.st_uid == os.geteuid() and (st.st_mode & 0o077) == 0, "Transaction directory must be private to its owner.")
    f = folder / "proposal.json"
    require(f.is_file() and not f.is_symlink() and f.stat().st_size <= 8192, "Invalid proposal.")
    plan = json.loads(f.read_bytes())
    require(plan["board"] == board.device and plan["board_id"] == BOARD and plan["schema"] == 1 and
            plan["package_sha256"] == PACKAGE_HASH and plan["application_sha256"] == APP_HASH, "Wrong device or release.")
    require(re.fullmatch(r"fw-[0-9a-f]{32}\.part", plan["inert_name"]), "Invalid transaction filename.")
    require(set(plan["settings"]) == set(SETTINGS), "Invalid settings snapshot.")
    return plan, json.loads((folder/"state.json").read_bytes())["phase"]


def approved(plan, approval):
    require(isinstance(approval, str) and secrets.compare_digest(proposal_digest(plan), approval),
            "Approval must match the reviewed exact proposal SHA-256.")


def check_time(plan, now):
    require(plan["expires"] == plan["created"] + 900 and plan["created"] <= now <= plan["expires"], "Proposal expired.")


def apply(board, folder, plan, phase, package, approval, now):
    approved(plan, approval)
    check_time(plan, now)
    require(phase in {"prepared", "uploading"}, "Promotion already attempted. Verify or reconcile before any further action.")
    require(sha((folder/"flash-before.bin").read_bytes()) == plan["prior_flash_sha256"] and
            sha((folder/"parameters-before.bin").read_bytes()) == plan["parameter_backup_sha256"], "Private backups failed verification.")
    board.guard(plan["board"])
    roots = board.root()
    require(not RESERVED.intersection(roots), "An SD bootloader trigger or result already exists.")
    before = flash_snapshot(board)
    require(sha(before[BASE:END]) == plan["previous_region_sha256"] and board.settings() == plan["settings"]
            and sha(board.read("@SYS/storage.bin", 32768)) == plan["parameter_backup_sha256"],
            "The aircraft state changed since proposal creation.")
    inert = plan["inert_name"]
    if inert in roots:
        require(phase == "uploading" and 0 <= roots[inert] <= len(package), "Inert path already belongs to another transaction.")
        part = board.read("/"+inert, roots[inert])
        require(part == package[:len(part)], "Inert contents are not this transaction's upload.")
        board.guard(plan["board"])
        board.remove(inert)
    store_phase(folder, "uploading")
    board.guard(plan["board"])
    board.upload(inert, package)
    require(board.root().get(inert) == len(package) and board.read("/"+inert, len(package)) == package,
            "Inert SD file failed full readback. No promotion attempted.")
    board.guard(plan["board"])
    require(not RESERVED.intersection(board.root()), "A bootloader marker appeared during upload.")
    store_phase(folder, "committing")
    board.promote(inert)
    roots = board.root()
    require(roots.get(TRIGGER) == len(package) and inert not in roots, "Promotion needs reconciliation.")
    store_phase(folder, "awaiting-cold-power-cycle")
    return {"status":"awaiting-cold-power-cycle", "package_sha256":PACKAGE_HASH}


def verify(board, folder, plan, phase, package, app, approval, cleanup):
    if cleanup:
        approved(plan, approval)
    require(phase in {"committing", "awaiting-cold-power-cycle", "verified", "cleaning", "complete"},
            "A promoted transaction is required.")
    board.guard(plan["board"])
    roots = board.root()
    pending = RESERVED.intersection(roots) - {COMPLETE}
    require(not pending, "Bootloader update is pending or interrupted: " + ", ".join(sorted(pending)))
    require(plan["inert_name"] not in roots, "Inert staging file remains. Check promotion history.")
    current = flash_snapshot(board)
    require(current[BASE:BASE+len(app)] == app and board.settings() == plan["settings"],
            "Flashed application or preserved settings failed readback.")
    board.health()
    if COMPLETE in roots:
        require(roots[COMPLETE] == len(package) and board.read("/"+COMPLETE, len(package)) == package,
                "Unexpected completed marker. Preserve it for examination.")
    else:
        require(phase in {"cleaning", "complete"}, "No success marker to confirm the bootloader transaction.")
    if cleanup:
        store_phase(folder, "cleaning")
        if COMPLETE in roots:
            board.guard(plan["board"])
            board.remove(COMPLETE)
        require(not RESERVED.intersection(board.root()), "Cleanup needs reconciliation.")
        store_phase(folder, "complete")
    elif phase != "complete":
        store_phase(folder, "verified" if COMPLETE in roots else "complete")
    return {"status":"verified", "application_sha256":APP_HASH, "marker_removed": cleanup or COMPLETE not in roots}


def transaction(board, action, bundle_dir, transaction_dir, approval=None, now=None):
    require(action in {"prepare", "apply", "verify", "cleanup"}, "Unknown firmware action.")
    package, app = load_package(bundle_dir)
    folder = Path(transaction_dir)
    clock = time.time if now is None else lambda: now
    if action == "prepare":
        return prepare(board, folder, app, clock)
    plan, phase = read_plan(folder, board)
    if action == "apply":
        return apply(board, folder, plan, phase, package, approval, int(clock()))
    return verify(board, folder, plan, phase, package, app, approval, action == "cleanup")


def run_firmware(link, action, bundle_dir, transaction_dir, approval=None):
    return transaction(Board(link), action, bundle_dir, transaction_dir, approval)
