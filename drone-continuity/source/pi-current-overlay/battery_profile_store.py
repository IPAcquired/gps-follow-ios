"""Durable, advisory per-physical-battery history; never a flight-control API.

A DataFlash BAT Inst identifies a monitor, NOT a physical battery. Each BIN hash
and monitor is therefore saved independently and remains UNASSIGNED until the
owner explicitly associates it with a registered physical pack. Registration,
observations and assignments are immutable checksummed records. No voltage,
capacity, file name or connection order is used to guess a pack's identity.

Writes use a private pending file, file fsync, a no-clobber hard-link commit and
directory fsync while holding a process lock. An interrupted write retains its
pending evidence; incomplete records never become a visible observation. All
history survives reopening; only summary *display* is bounded, never storage.
"""
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid


MAX_RECORD_BYTES = 32768
SCHEMA = 1
SHA = re.compile(r"[0-9a-f]{64}\Z")
DEFAULT_ROOT = Path.home() / "flight-data" / "batteries"
_COUNTS = {"voltage_samples", "current_samples", "integrated_intervals", "rejected_intervals"}
_NUMBERS = {
    "minimum_voltage_v": 100., "peak_current_a": 1000.,
    "measured_energy_wh": 1e12, "measured_charge_mah": 1e12,
    "measured_interval_seconds": 1e12, "mean_sampled_voltage_v": 100.,
    "mean_sampled_current_a": 1000., "mean_measured_power_w": 100000.,
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise ValueError("A lowercase SHA-256 of the actual BIN file is required")
    return value


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError("Pack identity must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Pack identity must be a canonical UUID") from exc
    if str(parsed) != value or parsed.version != 4:
        raise ValueError("Pack identity must be a canonical version-4 UUID")
    return value


def _instance(value):
    if isinstance(value, str) and re.fullmatch(r"[0-8]", value):
        value = int(value)
    if type(value) is not int or not 0 <= value <= 8:
        raise ValueError("BAT monitor instance must be an integer from 0 through 8")
    return value


def _label(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 80 or value != value.strip()
            or any(not ch.isprintable() for ch in value)):
        raise ValueError("Pack name must be 1–80 printable characters without surrounding whitespace")
    return value


def _metrics(value):
    if not isinstance(value, dict) or not value or set(value) - (_COUNTS | set(_NUMBERS) | {"energy_valid"}):
        raise ValueError("Only bounded battery measurement fields are accepted")
    for key, item in value.items():
        if key in _COUNTS:
            if type(item) is not int or not 0 <= item <= 10**12:
                raise ValueError("Battery sample counts must be nonnegative integers")
        elif key == "energy_valid":
            if type(item) is not bool:
                raise ValueError("Battery validity must be explicitly boolean")
        elif item is not None and (type(item) not in (int, float) or not math.isfinite(item)
                                   or not 0 <= item <= _NUMBERS[key]):
            raise ValueError("Battery measurements must be finite, bounded numbers or null")
    if value.get("energy_valid") is True and not (
        value.get("integrated_intervals", 0) > 0
        and value.get("measured_interval_seconds", 0) is not None
        and value.get("measured_interval_seconds", 0) > 0
        and value.get("measured_energy_wh") is not None
        and "measured_energy_wh" in value
    ):
        raise ValueError("Valid measured energy requires an actual integrated interval")
    return json.loads(_canonical(value))  # Detached immutable snapshot, not caller-owned state.


def _directory(path):
    """Create/check every ancestor without accepting symlinks or junctions."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Parent traversal is not accepted for the battery store")
    path = path.absolute()
    for item in reversed([path, *path.parents]):
        try:
            item.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            _fsync_directory(item.parent)
        info = item.lstat()
        if (not stat.S_ISDIR(info.st_mode) or item.is_symlink()
                or (hasattr(item, "is_junction") and item.is_junction())):
            raise ValueError("Battery store paths must be real directories, not links")
    return path


def _fsync_directory(path):
    if os.name == "nt":
        return  # Board uses Linux/ext4; Windows fixtures cannot directory-fsync.
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextlib.contextmanager
def _locked(root, read_only=False):
    if read_only:
        root = Path(root).absolute()
        if ".." in root.parts:
            raise ValueError("Battery history path cannot traverse parents")
        for directory in [root, *root.parents, *(root / child for child in ("packs", "observations", "assignments", "pending"))]:
            if not directory.is_dir() or directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
                raise ValueError("Read-only battery history requires real existing directories")
    else:
        root = _directory(root)
        for child in ("packs", "observations", "assignments", "pending"):
            _directory(root / child)
    lock_path = root / ".lock"
    if lock_path.is_symlink():
        raise ValueError("Battery store lock cannot be a link")
    descriptor = os.open(lock_path, (os.O_RDONLY if read_only else os.O_RDWR | os.O_CREAT) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Battery store lock must be a private regular file")
        if os.name == "nt":
            import msvcrt
            if info.st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_SH if read_only else fcntl.LOCK_EX)
        yield root
    finally:
        if os.name == "nt":
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        os.close(descriptor)


def _payload(kind, identity, **body):
    return {"schema": SCHEMA, "kind": kind, "id": identity,
            "revision_id": str(uuid.uuid4()), "created_unix": time.time(),
            "authority": "advisory_only", **body}


def _commit(root, directory, identity, payload):
    record = {"payload": payload, "sha256": _hash(payload)}
    raw = _canonical(record) + b"\n"
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("Battery record exceeds its single-record size bound")
    pending = root / "pending" / (str(uuid.uuid4()) + ".pending")
    destination = root / directory / (identity + ".json")
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(root / "pending")
    os.link(pending, destination, follow_symlinks=False)  # Never replace an existing record.
    _fsync_directory(root / directory)
    pending.unlink()
    _fsync_directory(root / "pending")
    return record


def _no_duplicate_keys(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("Duplicate keys in a battery record")
        output[key] = value
    return output


def _read(path):
    if path.is_symlink():
        raise ValueError("Battery records cannot be links")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_RECORD_BYTES:
            raise ValueError("Invalid battery record type or size")
        raw = stream.read(MAX_RECORD_BYTES + 1)
    try:
        record = json.loads(raw, object_pairs_hook=_no_duplicate_keys,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Battery record is malformed; history was not changed") from exc
    if (not isinstance(record, dict) or set(record) != {"payload", "sha256"}
            or not isinstance(record["payload"], dict) or _sha(record["sha256"]) != _hash(record["payload"])):
        raise ValueError("Battery history integrity check failed; history was not changed")
    return record


def _observation_id(log_sha, instance):
    return _hash({"log_sha256": _sha(log_sha), "instance": _instance(instance)})


def _load(root):
    result = {"packs": {}, "observations": {}, "assignments": {}}
    base_keys = {"schema", "kind", "id", "revision_id", "created_unix", "authority"}
    bodies = {"packs": {"label"}, "observations": {"log_sha256", "instance", "metrics"},
              "assignments": {"observation_id", "pack_id", "observation_sha256", "pack_sha256"}}
    kind_for = {"packs": "pack", "observations": "observation", "assignments": "assignment"}
    for directory in result:
        for path in sorted((root / directory).iterdir()):
            record = _read(path)
            body = record["payload"]
            if (set(body) != base_keys | bodies[directory] or body["schema"] != SCHEMA
                    or type(body["schema"]) is not int or body["kind"] != kind_for[directory]
                    or body["authority"] != "advisory_only"
                    or path.name != str(body["id"]) + ".json"
                    or type(body["created_unix"]) not in (int, float)
                    or not math.isfinite(body["created_unix"]) or body["created_unix"] <= 0):
                raise ValueError("Battery record schema or identity is invalid")
            _uuid(body["revision_id"])
            if directory == "packs":
                _uuid(body["id"])
                _label(body["label"])
            elif directory == "observations":
                if body["id"] != _observation_id(body["log_sha256"], body["instance"]):
                    raise ValueError("Battery observation identity conflicts with its source")
                _metrics(body["metrics"])
            else:
                if _sha(body["id"]) != _sha(body["observation_id"]):
                    raise ValueError("Battery assignment identity is invalid")
                _uuid(body["pack_id"])
                _sha(body["observation_sha256"])
                _sha(body["pack_sha256"])
            result[directory][body["id"]] = record
    labels = [pack["payload"]["label"].casefold() for pack in result["packs"].values()]
    if len(labels) != len(set(labels)):
        raise ValueError("Duplicate physical-pack names in battery history")
    for identity, record in result["assignments"].items():
        body = record["payload"]
        observation = result["observations"].get(identity)
        pack = result["packs"].get(body["pack_id"])
        if (observation is None or pack is None or observation["sha256"] != body["observation_sha256"]
                or pack["sha256"] != body["pack_sha256"]):
            raise ValueError("Battery assignment references missing or changed immutable evidence")
    result["pending_count"] = 0
    for path in (root / "pending").iterdir():
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or not re.fullmatch(r"[0-9a-f-]{36}\.pending", path.name):
            raise ValueError("Invalid interrupted-write evidence in battery store")
        _uuid(path.stem)
        if info.st_size > MAX_RECORD_BYTES:
            raise ValueError("Interrupted battery record exceeds its single-record bound")
        result["pending_count"] += 1
    return result


def _pack_view(record):
    body = record["payload"]
    return {"pack_id": body["id"], "label": body["label"],
            "registered_unix": body["created_unix"], "record_sha256": record["sha256"]}


def _view(state, identity):
    record = state["observations"][identity]
    body = record["payload"]
    assignment = state["assignments"].get(identity)
    pack_id = assignment["payload"]["pack_id"] if assignment else None
    return {"observation_id": identity, "log_sha256": body["log_sha256"],
            "instance": body["instance"], "metrics": body["metrics"],
            "observed_unix": body["created_unix"], "pack_id": pack_id,
            "time_basis": "saved_to_store_not_flight_time",
            "pack_label": state["packs"][pack_id]["payload"]["label"] if pack_id else None,
            "record_sha256": record["sha256"], "assignment_sha256": assignment["sha256"] if assignment else None}


def register_pack(root, label):
    """Explicit owner-named physical pack. Repeating the exact name is idempotent."""
    label = _label(label)
    with _locked(root) as root:
        state = _load(root)
        for record in state["packs"].values():
            previous = record["payload"]["label"]
            if previous == label:
                return _pack_view(record)
            if previous.casefold() == label.casefold():
                raise ValueError("That physical-pack name already exists with different capitalization")
        identity = str(uuid.uuid4())
        return _pack_view(_commit(root, "packs", identity, _payload("pack", identity, label=label)))


def save_observation(root, log_sha, instance, metrics):
    """Persist one log+monitor; never infer physical identity or replace its metrics."""
    log_sha, instance, metrics = _sha(log_sha), _instance(instance), _metrics(metrics)
    identity = _observation_id(log_sha, instance)
    with _locked(root) as root:
        state = _load(root)
        previous = state["observations"].get(identity)
        if previous:
            if previous["payload"]["metrics"] != metrics:
                raise ValueError("Different metrics for the same immutable BIN/monitor; original history preserved")
        else:
            state["observations"][identity] = _commit(root, "observations", identity, _payload(
                "observation", identity, log_sha256=log_sha, instance=instance, metrics=metrics))
        return _view(state, identity)


def assign_pack(root, log_sha, instance, pack_id):
    """Explicit binding; a conflicting reassignment is rejected, never overwritten."""
    identity, pack_id = _observation_id(log_sha, instance), _uuid(pack_id)
    with _locked(root) as root:
        state = _load(root)
        if identity not in state["observations"] or pack_id not in state["packs"]:
            raise ValueError("Both the saved BIN/monitor and registered physical pack must exist")
        assignment = state["assignments"].get(identity)
        if assignment:
            if assignment["payload"]["pack_id"] != pack_id:
                raise ValueError("This observation is already assigned to another physical pack; history preserved")
        else:
            state["assignments"][identity] = _commit(root, "assignments", identity, _payload(
                "assignment", identity, observation_id=identity, pack_id=pack_id,
                observation_sha256=state["observations"][identity]["sha256"],
                pack_sha256=state["packs"][pack_id]["sha256"]))
        return _view(state, identity)


def list_observations(root, read_only=False):
    """Full persisted history, sorted oldest-first; not limited by UI display size."""
    with _locked(root, read_only=read_only) as root:
        state = _load(root)
        return sorted((_view(state, identity) for identity in state["observations"]),
                      key=lambda value: (value["observed_unix"], value["observation_id"]))


def _aggregate(observations):
    valid = [entry["metrics"] for entry in observations if entry["metrics"].get("energy_valid") is True]
    duration = sum(value["measured_interval_seconds"] for value in valid)
    energy = sum(value["measured_energy_wh"] for value in valid)
    voltages = [entry["metrics"]["minimum_voltage_v"] for entry in observations
                if entry["metrics"].get("minimum_voltage_v") is not None]
    currents = [entry["metrics"]["peak_current_a"] for entry in observations
                if entry["metrics"].get("peak_current_a") is not None]
    charge = [value.get("measured_charge_mah") for value in valid]
    overlaps = len({entry["log_sha256"] for entry in observations}) != len(observations)
    return {"energy_valid_observations": len(valid),
            "overlapping_monitor_observations": overlaps,
            "measured_energy_wh": energy if valid and not overlaps else None,
            "measured_charge_mah": sum(charge) if not overlaps and charge and all(value is not None for value in charge) else None,
            "measured_interval_seconds": duration if valid and not overlaps else None,
            "minimum_voltage_v": min(voltages) if voltages else None,
            "peak_current_a": max(currents) if currents else None,
            "mean_measured_power_w": energy * 3600 / duration if duration and not overlaps else None}


def summary(root, limit=200):
    """All-history totals and distinct pack measurements; latest bounded UI records."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Summary display limit must be an integer from 1 through 500")
    with _locked(root) as root:
        state = _load(root)
        observations = sorted((_view(state, identity) for identity in state["observations"]),
                              key=lambda value: (value["observed_unix"], value["observation_id"]), reverse=True)
        shown = observations[:limit]
        packs = []
        for record in sorted(state["packs"].values(), key=lambda record: record["payload"]["label"].casefold()):
            pack = _pack_view(record)
            history = [entry for entry in observations if entry["pack_id"] == pack["pack_id"]]
            packs.append({**pack, "observation_count": len(history), "summary": _aggregate(history),
                          "monitor_summaries": [
                              {"instance": instance, **_aggregate([entry for entry in history if entry["instance"] == instance])}
                              for instance in sorted({entry["instance"] for entry in history})],
                          "observations": [entry for entry in shown if entry["pack_id"] == pack["pack_id"]]})
        return {"schema": SCHEMA, "authority": "advisory_only", "state": "ok",
                "packs": packs, "observations": shown,
                "unassigned": [entry for entry in shown if entry["pack_id"] is None],
                "pack_count": len(packs), "observation_count": len(observations),
                "unassigned_count": sum(entry["pack_id"] is None for entry in observations),
                "pending_record_count": state["pending_count"], "history_display_limit": limit,
                "history_truncated": len(observations) > limit,
                "identity_policy": "Manual physical-pack UUID; BAT Inst is only a monitor; no identity guessing.",
                "comparison_caution": "Unmatched measured intervals do not establish relative battery health, capacity or efficiency.",
                "may_write_ardupilot_parameters": False, "may_command_actuators": False}
