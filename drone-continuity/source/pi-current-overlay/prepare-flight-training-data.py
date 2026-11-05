#!/usr/bin/env python3
"""Prepare immutable real-telemetry battery targets, without inventing labels.

Only reads completed local BIN files. ARM indicates armed, not necessarily
airborne. BAT voltage/current are physical measurements; next voltage is an
observation-supervised target, never a human obstacle/avoidance label.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import uuid

from flight_efficiency_metrics import FlightEfficiencyMetrics
import battery_profile_store as durable

ALGORITHM = "battery-next-voltage-preparation-v2"
LABEL_SOURCE = "observed_telemetry_not_human_reviewed"
MAX_LINE_BYTES = 4096


def sha_file(path, guard=None):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            if guard:
                guard()
            digest.update(data)
    return digest.hexdigest()


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def decoded_messages(path):
    from pymavlink import mavutil
    log = mavutil.mavlink_connection(str(path), robust_parsing=True)
    try:
        while (message := log.recv_match(blocking=False)) is not None:
            yield message.get_type(), message.to_dict()
    finally:
        log.close()


def extract_messages(messages, log_sha, emit, source_order=None):
    """Streaming parser interface also usable directly by the onboard analyzer."""
    durable._sha(log_sha)
    previous, origins, counts, armed = {}, {}, Counter(), None
    efficiency = FlightEfficiencyMetrics()
    firmware = {}
    parameters = {}
    battery_fields = set()
    armed_events, armed_segments, pair_count, armed_pairs, current_pairs = 0, 0, 0, 0, 0
    last_arm_stamp = -1.
    for kind, values in messages:
        counts[kind] += 1
        efficiency.observe(kind, values)
        if kind == "VER":
            firmware = {key: value for key in ("BT", "BST", "Maj", "Min", "Pat", "FWT", "GH", "FWS", "APJ", "BU")
                        if type(value := values.get(key)) in (int, float, str)
                        and (not isinstance(value, str) or len(value) <= 128)
                        and (not isinstance(value, float) or math.isfinite(value))}
        elif kind == "PARM":
            name = values.get("Name")
            value = number(values.get("Value"), -1e20, 1e20)
            if isinstance(name, str) and 0 < len(name) <= 32 and value is not None:
                parameters[name.strip("\0 ")] = value
        elif kind == "ARM":
            stamp = number(values.get("TimeUS"), 0, 1e16)
            state = values.get("ArmState")
            if stamp is not None and stamp >= last_arm_stamp and type(state) in (bool, int) and state in (0, 1):
                armed_events += 1
                armed_segments += int(bool(state) and armed is not True)
                armed, last_arm_stamp = bool(state), stamp
        if kind != "BAT":
            continue
        battery_fields.update(key for key in ("TimeUS", "Inst", "Volt", "Curr", "H", "EnrgTot", "CurrTot") if key in values)
        instance = values.get("Inst")
        if type(instance) is not int or not 0 <= instance <= 8:
            counts["BAT_invalid_instance"] += 1
            continue
        stamp = number(values.get("TimeUS"), 0, 1e16)
        volts = number(values.get("Volt"), .001, 100)
        amps = number(values.get("Curr"), 0, 1000)
        # Explicit healthy state is required for training. Unknown is not healthy.
        health = values.get("H")
        if stamp is None or volts is None or type(health) not in (bool, int) or health != 1:
            previous.pop(instance, None)
            counts["BAT_invalid_training_reading"] += 1
            continue
        if amps is None:
            counts["BAT_current_unknown"] += 1
        current_armed = armed if stamp >= last_arm_stamp else None
        reading = {"time_us": stamp, "voltage_v": volts, "current_a": amps, "armed": current_armed}
        prior = previous.get(instance)
        if prior is not None:
            elapsed = (stamp - prior["time_us"]) / 1e6
            if 0 < elapsed < 1:
                counts["BAT_below_one_second_sampling"] += 1
                continue
            if not 1 <= elapsed <= 10:
                counts["BAT_rejected_time_interval"] += 1
                previous.pop(instance, None)
                if elapsed <= 0:
                    origins.pop(instance, None)
                prior = None
        origins.setdefault(instance, stamp)
        if prior is not None:
            both_armed = True if prior["armed"] is True and current_armed is True else (
                False if prior["armed"] is False and current_armed is False else None)
            row = {
                "schema": 1, "kind": "battery_next_voltage", "flight_log_sha256": log_sha,
                "instance": instance, "sequence": pair_count, "time_us": prior["time_us"],
                "target_time_us": stamp, "voltage_v": prior["voltage_v"],
                "current_a": prior["current_a"], "current_measured": prior["current_a"] is not None,
                "elapsed_seconds": max(0., (prior["time_us"] - origins[instance]) / 1e6),
                "delta_seconds": elapsed, "target_voltage_v": volts,
                "armed": both_armed, "synthetic": False, "label_source": LABEL_SOURCE,
                "sensor_calibration_sha256": None, "software_sha256": None,
                "source_order": source_order, "may_command_actuators": False,
                "may_write_ardupilot_parameters": False,
            }
            raw = durable._canonical(row) + b"\n"
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError("Prepared battery record exceeds its bound")
            emit(raw)
            pair_count += 1
            armed_pairs += int(both_armed is True)
            current_pairs += int(prior["current_a"] is not None)
        previous[instance] = reading
    if not sum(counts.values()):
        raise ValueError("No DataFlash records decoded")
    return {
        "schema": 1, "algorithm": ALGORITHM, "flight_log_sha256": log_sha,
        "synthetic": False, "label_source": LABEL_SOURCE, "source_order": source_order,
        "sensor_calibration_sha256": None, "software_sha256": None,
        "firmware_fields_observed": firmware or None,
        "parameter_snapshot_sha256": durable._hash(parameters) if parameters else None,
        "message_counts": dict(sorted(counts.items())), "battery_fields_observed": sorted(battery_fields),
        "battery_prediction_pairs": pair_count, "armed_prediction_pairs": armed_pairs,
        "current_measured_prediction_pairs": current_pairs,
        "current_unknown_prediction_pairs": pair_count - current_pairs,
        "armed_status_records": armed_events, "observed_armed_segments": armed_segments,
        "airborne_flight_confirmed": False, "airborne_evidence": "unknown; arming is not proof of takeoff",
        "efficiency_and_control_observations": efficiency.report(),
        "sample_policy": "Healthy measured BAT voltage; current remains null when unmeasured, never inferred0A. Sampled at >=1 second with 1–10 second target intervals.",
        "obstacle_avoidance_labels": "unavailable; never fabricated from battery data",
        "authority": "candidate_training_data_only", "automatic_activation": False,
        "may_command_actuators": False, "may_write_ardupilot_parameters": False,
    }


def prepare_bin(path, expected_sha, output_root, expected_size=None, source_order=None, decoder=decoded_messages, guard=None):
    path = Path(path)
    durable._sha(expected_sha)
    if path.is_symlink() or not path.is_file() or (expected_size is not None and path.stat().st_size != expected_size):
        raise ValueError("Completed BIN file type or size does not match its receipt")
    if guard:
        guard()
    if sha_file(path, guard) != expected_sha:
        raise ValueError("Completed BIN SHA-256 does not match its receipt")
    output_root = durable._directory(output_root)
    with durable._locked(output_root) as output_root:
        prepared = durable._directory(output_root / "prepared")
        target = prepared / expected_sha
        if target.exists():
            if target.is_symlink():
                raise ValueError("Prepared log directory cannot be a link")
            metadata = read_metadata(target, guard)
            if metadata["flight_log_sha256"] != expected_sha or metadata.get("algorithm") != ALGORITHM:
                raise ValueError("Existing prepared log identity conflicts; evidence preserved")
            return metadata
        pending = prepared / (".pending-" + str(uuid.uuid4()))
        pending.mkdir(mode=0o700)
        sample_path = pending / "samples.jsonl"
        def guarded_messages():
            iterator = decoder(path)
            try:
                for index, message in enumerate(iterator):
                    if guard and index % 512 == 0:
                        guard()
                    yield message
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
        with sample_path.open("xb") as stream:
            metadata = extract_messages(guarded_messages(), expected_sha, stream.write, source_order)
            stream.flush()
            os.fsync(stream.fileno())
        # Fail closed if the source changed while decoding.
        if sha_file(path, guard) != expected_sha:
            raise ValueError("BIN changed during preparation; pending evidence retained")
        metadata.update({"source_bytes": path.stat().st_size, "samples_sha256": sha_file(sample_path),
                         "samples_bytes": sample_path.stat().st_size})
        with (pending / "metadata.json").open("xb") as stream:
            stream.write(durable._canonical(metadata) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        durable._fsync_directory(pending)
        if target.exists():
            raise ValueError("Prepared log appeared concurrently; pending evidence retained")
        pending.rename(target)  # Under process lock; only complete directories become visible.
        durable._fsync_directory(prepared)
        return metadata


def read_metadata(directory, guard=None):
    directory = Path(directory)
    metadata_path, samples = directory / "metadata.json", directory / "samples.jsonl"
    if directory.is_symlink() or metadata_path.is_symlink() or samples.is_symlink():
        raise ValueError("Prepared training records cannot be links")
    if not metadata_path.is_file() or metadata_path.stat().st_size > 32768 or not samples.is_file():
        raise ValueError("Prepared training artifact is incomplete or oversized")
    metadata = json.loads(metadata_path.read_bytes())
    if (metadata.get("schema") != 1 or metadata.get("algorithm") != ALGORITHM
            or metadata.get("samples_bytes") != samples.stat().st_size
            or metadata.get("samples_sha256") != sha_file(samples, guard)):
        raise ValueError("Prepared training artifact integrity failed")
    durable._sha(metadata.get("flight_log_sha256"))
    if directory.name != metadata["flight_log_sha256"]:
        raise ValueError("Prepared artifact directory identity failed")
    return metadata


def prepare_receipt(receipt_path, output_root):
    receipt_path = Path(receipt_path)
    if receipt_path.is_symlink() or receipt_path.stat().st_size > 1024 * 1024:
        raise ValueError("Invalid download receipt")
    receipt = json.loads(receipt_path.read_bytes())
    if (type(receipt.get("flight_setting_writes")) is not int or receipt.get("flight_setting_writes") != 0
            or receipt.get("source_logs_erased") is not False):
        raise ValueError("Read-only download provenance is missing")
    completed = receipt.get("downloaded")
    if not isinstance(completed, list):
        raise ValueError("Completed download list is required")
    reports = []
    for item in completed:
        if not isinstance(item, dict):
            raise ValueError("Completed download entry is not an object")
        digest = durable._sha(item.get("sha256"))
        # Use the exact SHA-named file beside the private receipt, never arbitrary paths.
        if PureWindowsPath(str(item.get("path", ""))).name != digest + ".BIN":
            raise ValueError("Download file identity is not SHA-named")
        size, order = item.get("size"), item.get("log_id")
        if type(size) is not int or size <= 0 or type(order) is not int or not 0 <= order <= 65535:
            raise ValueError("Download size or source log order is invalid")
        reports.append(prepare_bin(receipt_path.parent / (digest + ".BIN"), digest,
                                   output_root, expected_size=size, source_order=order))
    return {"schema": 1, "state": "prepared" if reports else "waiting_completed_downloads",
            "completed_logs": len(reports), "battery_prediction_pairs": sum(report["battery_prediction_pairs"] for report in reports),
            "armed_prediction_pairs": sum(report["armed_prediction_pairs"] for report in reports),
            "current_measured_prediction_pairs": sum(report["current_measured_prediction_pairs"] for report in reports),
            "current_unknown_prediction_pairs": sum(report["current_unknown_prediction_pairs"] for report in reports),
            "logs_with_armed_segments": sum(report["observed_armed_segments"] > 0 for report in reports),
            "airborne_flight_confirmed": False, "obstacle_avoidance_labels_available": False,
            "automatic_activation": False, "reports": reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--bin", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if args.receipt and not args.bin:
        result = prepare_receipt(args.receipt, args.output_root)
    elif args.bin and args.sha256 and not args.receipt:
        result = prepare_bin(args.bin, args.sha256, args.output_root)
    else:
        parser.error("Use either --receipt or --bin with --sha256")
    if args.summary_only and "reports" in result:
        result = {key: value for key, value in result.items() if key != "reports"}
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
