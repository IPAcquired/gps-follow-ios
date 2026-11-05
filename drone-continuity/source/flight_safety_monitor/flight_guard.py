#!/usr/bin/env python3
"""ArduPilot flight safety monitor and guarded PID proposal tool.

The deterministic analyzer owns every measurement and every parameter limit.
An optional local Ollama model can turn the finished report into plain English,
but model output is never parsed as commands and never reaches the write path.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SERIAL_DEPS = ROOT / "work" / "serial-deps"
if SERIAL_DEPS.exists():
    sys.path.insert(0, str(SERIAL_DEPS))

from pymavlink import mavutil  # noqa: E402
from pymavlink.DFReader import DFReader_binary  # noqa: E402


VERSION = "0.1.0"
DEFAULT_OUTPUT = ROOT / "outputs" / "flight-safety-monitor"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
PID_ALLOWLIST = {
    "ATC_RAT_RLL_P", "ATC_RAT_RLL_I", "ATC_RAT_RLL_D",
    "ATC_RAT_PIT_P", "ATC_RAT_PIT_I", "ATC_RAT_PIT_D",
}
PROTECTED_PREFIXES = (
    "SERIAL", "MAV", "FRAME_", "MOT_PWM", "SERVO", "RC", "FLTMODE",
    "BATT", "FS_", "ARMING", "RNGFND", "PRX", "AVOID", "INS_HNTCH",
    "INS_GYRO", "INS_ACCEL", "COMPASS", "GPS", "EK3", "AHRS",
)
PROTECTED_EXACT = {
    "MOT_SPIN_MIN", "MOT_SPIN_ARM", "MOT_THST_EXPO", "BRD_TYPE",
    "FORMAT_VERSION", "SYSID_THISMAV", "CAN_P1_DRIVER", "CAN_P2_DRIVER",
}
AUTO_CHANGING = {
    "STAT_RUNTIME", "STAT_FLTTIME", "STAT_BOOTCNT", "STAT_RESET",
    "BARO_GND_PRESS", "BARO2_GND_PRESS", "COMPASS_DEC",
}
MAX_SINGLE_CHANGE_FRACTION = 0.10
MIN_AIRBORNE_SECONDS = 5.0
PARAMETER_BOUNDS = {
    "ATC_RAT_RLL_P": (0.02, 0.25), "ATC_RAT_PIT_P": (0.02, 0.25),
    "ATC_RAT_RLL_I": (0.02, 0.30), "ATC_RAT_PIT_I": (0.02, 0.30),
    "ATC_RAT_RLL_D": (0.0005, 0.02), "ATC_RAT_PIT_D": (0.0005, 0.02),
}
CALIBRATION_PREFIXES = ("INS_ACC", "INS_GYR", "COMPASS_OFS", "COMPASS_DIA", "COMPASS_ODI", "BARO_GND")


def assess_live_readiness(events: list[dict[str, Any]], bench_mode: bool = False, stale_after_s: float = 3.0) -> dict[str, Any]:
    """Deterministic live GO/NO-GO gate from sanitized telemetry events."""
    blockers: list[str] = []
    limitations: list[str] = []
    passes: list[str] = []
    if not events:
        return {"decision": "NO-GO", "blockers": ["No live telemetry received."], "limitations": [], "passes": []}
    now = max(float(item.get("elapsed_s", 0.0)) for item in events)
    recent = [item for item in events if now - float(item.get("elapsed_s", 0.0)) <= 12.0]
    latest = {}
    for item in events:
        latest[str(item.get("type", ""))] = item
    heartbeat = latest.get("HEARTBEAT")
    if not heartbeat or now - float(heartbeat.get("elapsed_s", 0.0)) > stale_after_s:
        blockers.append("Flight-controller heartbeat is missing or stale.")
    elif int(heartbeat.get("data", {}).get("base_mode", 0)) & 128:
        blockers.append("Aircraft is armed.")
    else:
        passes.append("Controller heartbeat is current and aircraft is disarmed.")
    texts = [str(item.get("data", {}).get("text", item.get("data", {}).get("Text", ""))) for item in recent if item.get("type") == "STATUSTEXT"]
    lowered = [text.lower() for text in texts]
    compass_terms = ("mag field", "compass not", "compass inconsistent", "compass variance", "compass offsets")
    compass = next((text for text in reversed(texts) if any(term in text.lower() for term in compass_terms)), None)
    if compass:
        blockers.append(compass)
    rc = latest.get("RC_CHANNELS", {}).get("data", {})
    radio_present = int(rc.get("chancount", 0) or 0) >= 4 and int(rc.get("chan3_raw", 0) or 0) not in (0, 65535)
    radio_events = [text for text in lowered if "radio failsafe" in text]
    radio_failsafe = bool(radio_events and "clear" not in radio_events[-1])
    if radio_present and not radio_failsafe:
        passes.append("Receiver is supplying live RC channels without a recent failsafe message.")
    elif bench_mode and not radio_present:
        limitations.append("Transmitter/receiver is intentionally disconnected; radio failsafe is not verified.")
    else:
        blockers.append("Radio link is absent or a recent radio-failsafe message is active.")
    battery_mv = int(latest.get("SYS_STATUS", {}).get("data", {}).get("voltage_battery", 0) or 0)
    battery_present = battery_mv > 5000
    battery_low = any("battery" in text and ("below" in text or "failsafe" in text) for text in lowered)
    if battery_present and not battery_low:
        passes.append(f"Flight battery telemetry is present ({battery_mv / 1000.0:.2f} V).")
    elif bench_mode and not battery_present:
        limitations.append("Flight battery is intentionally disconnected; voltage and battery failsafes are not verified.")
    else:
        blockers.append("Flight-battery telemetry is absent or reports a low/failsafe condition.")
    gps_item = latest.get("GPS_RAW_INT")
    gps_fresh = bool(gps_item and now - float(gps_item.get("elapsed_s", 0.0)) <= stale_after_s)
    gps = gps_item.get("data", {}) if gps_item else {}
    if gps_fresh and int(gps.get("fix_type", 0) or 0) >= 3:
        passes.append(f"GPS has a fresh 3D fix with {int(gps.get('satellites_visible', 0) or 0)} satellites.")
    else:
        blockers.append("GPS telemetry is missing, stale, or lacks a 3D fix.")
    ekf_item = latest.get("EKF_STATUS_REPORT")
    ekf_fresh = bool(ekf_item and now - float(ekf_item.get("elapsed_s", 0.0)) <= stale_after_s)
    ekf_flags = int(ekf_item.get("data", {}).get("flags", 0) or 0) if ekf_item else 0
    if ekf_fresh and ekf_flags & 0x1F == 0x1F:
        passes.append("EKF attitude, velocity, and position solution flags are current.")
    else:
        blockers.append("EKF status is missing, stale, or lacks the required navigation solution flags.")
    ranges = {(int(item.get("data", {}).get("id", -1)), int(item.get("data", {}).get("orientation", -1))) for item in recent if item.get("type") == "DISTANCE_SENSOR"}
    expected = {(2, 25), (10, 0), (12, 2), (16, 6)}
    if expected.issubset(ranges):
        passes.append("All four expected rangefinder IDs and orientations are fresh.")
    else:
        blockers.append(f"Fresh rangefinder streams are incomplete ({len(expected & ranges)}/4 expected streams).")
    return {"decision": "GO" if not blockers and not limitations else "NO-GO", "blockers": blockers, "limitations": limitations, "passes": passes, "evaluated_elapsed_s": now}


def summarize_pid_filter_parameters(parameters: dict[str, Any]) -> dict[str, float | None]:
    """Return a bounded, display-only PID/filter snapshot from a full readback."""
    names = (
        "ATC_RAT_RLL_P", "ATC_RAT_RLL_I", "ATC_RAT_RLL_D",
        "ATC_RAT_PIT_P", "ATC_RAT_PIT_I", "ATC_RAT_PIT_D",
        "ATC_RAT_YAW_P", "ATC_RAT_YAW_I", "ATC_RAT_YAW_D",
        "INS_GYRO_FILTER", "INS_ACCEL_FILTER", "INS_HNTCH_ENABLE",
        "INS_HNTCH_MODE", "INS_HNTCH_FREQ", "INS_HNTCH_BW", "INS_HNTCH_ATT",
    )
    result = {}
    for name in names:
        raw = parameters.get(name)
        if isinstance(raw, dict):
            raw = raw.get("value")
        result[name] = finite_number(raw)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: Iterable[float], q: float) -> float | None:
    data = np.asarray(list(values), dtype=float)
    return None if not len(data) else float(np.percentile(data, q * 100.0))


def rms(values: Iterable[float]) -> float:
    data = np.asarray(list(values), dtype=float)
    return 0.0 if not len(data) else float(np.sqrt(np.mean(data * data)))


def finite_number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def is_protected(name: str) -> bool:
    return name in PROTECTED_EXACT or name.startswith(PROTECTED_PREFIXES)


def armed_intervals(rows: dict[str, list[tuple[float, dict[str, Any]]]]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    armed_at = None
    last_time = 0.0
    for values in rows.values():
        if values:
            last_time = max(last_time, values[-1][0])
    for stamp, item in rows.get("ARM", []):
        state = int(item.get("ArmState", 0))
        if state == 1 and armed_at is None:
            armed_at = stamp
        elif state == 0 and armed_at is not None:
            intervals.append((armed_at, stamp))
            armed_at = None
    if armed_at is not None:
        intervals.append((armed_at, last_time))
    return [pair for pair in intervals if pair[1] > pair[0]]


def longest_armed_interval(rows: dict[str, list[tuple[float, dict[str, Any]]]]) -> tuple[float, float] | None:
    intervals = armed_intervals(rows)
    return max(intervals, key=lambda pair: pair[1] - pair[0]) if intervals else None


def screening_interval(interval: tuple[float, float], margin_s: float = 3.0) -> tuple[float, float]:
    """Exclude arm-up and touchdown transients from tuning safety statistics."""
    start, end = interval
    if end - start > 2 * margin_s + MIN_AIRBORNE_SECONDS:
        return start + margin_s, end - margin_s
    return interval


def spectrum(samples: list[tuple[float, float]], low_hz: float = 4.0, high_hz: float = 25.0) -> dict[str, Any]:
    if len(samples) < 64:
        return {"usable": False, "reason": "too_few_samples"}
    stamps = np.asarray([item[0] for item in samples], dtype=float)
    values = np.asarray([item[1] for item in samples], dtype=float)
    diffs = np.diff(stamps)
    diffs = diffs[(diffs > 0) & (diffs < 0.2)]
    if len(diffs) < 20:
        return {"usable": False, "reason": "irregular_timing"}
    sample_hz = float(1.0 / np.median(diffs))
    if sample_hz < high_hz * 2.2:
        return {"usable": False, "reason": "sample_rate_too_low", "sample_hz": sample_hz}
    grid = np.arange(stamps[0], stamps[-1], 1.0 / sample_hz)
    if len(grid) < 64:
        return {"usable": False, "reason": "window_too_short"}
    signal = np.interp(grid, stamps, values)
    signal -= np.polyval(np.polyfit(np.arange(len(signal)), signal, 1), np.arange(len(signal)))
    windowed = signal * np.hanning(len(signal))
    amplitudes = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(len(windowed), d=1.0 / sample_hz)
    mask = (frequencies >= low_hz) & (frequencies <= high_hz)
    if not np.any(mask):
        return {"usable": False, "reason": "no_frequency_bins"}
    band_amp = amplitudes[mask]
    band_freq = frequencies[mask]
    peak_index = int(np.argmax(band_amp))
    peak = float(band_amp[peak_index])
    floor = float(np.median(band_amp)) or 1e-9
    return {
        "usable": True,
        "sample_hz": sample_hz,
        "peak_hz": float(band_freq[peak_index]),
        "peak_to_median_ratio": peak / floor,
        "signal_rms": rms(signal),
    }


def rangefinder_health(rows: dict[str, list[tuple[float, dict[str, Any]]]], interval: tuple[float, float]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in ("RFND", "PRX", "DIST"):
        samples = [item for stamp, item in rows.get(kind, []) if interval[0] <= stamp <= interval[1]]
        if not samples:
            continue
        numeric_fields = sorted({
            key for item in samples for key, value in item.items()
            if key not in {"mavpackettype", "TimeUS", "I", "Instance"}
            and finite_number(value) is not None
            and any(token in key.lower() for token in ("dist", "range", "distance"))
        })
        fields = {}
        for field in numeric_fields:
            values = [finite_number(item.get(field)) for item in samples]
            valid = [value for value in values if value is not None and value > 0]
            fields[field] = {
                "samples": len(values),
                "valid_samples": len(valid),
                "dropout_fraction": 1.0 - len(valid) / max(1, len(values)),
                "median": float(statistics.median(valid)) if valid else None,
            }
        result[kind] = {"message_samples": len(samples), "fields": fields}
    return result


def summarize_armed_interval(
    rows: dict[str, list[tuple[float, dict[str, Any]]]],
    interval: tuple[float, float],
    index: int,
) -> dict[str, Any]:
    start, end = interval
    screen_start, screen_end = screening_interval(interval)
    result: dict[str, Any] = {
        "index": index,
        "start_s": start,
        "end_s": end,
        "duration_s": end - start,
        "screening_start_s": screen_start,
        "screening_end_s": screen_end,
        "modes": [],
        "control": {},
        "vibration": {},
        "motors": {},
        "power": {},
        "rangefinders": rangefinder_health(rows, interval),
        "errors": [],
        "notable_messages": [],
        "blockers": [],
    }
    result["modes"] = [
        {"time_s": stamp, "mode": item.get("Mode", item.get("ModeNum"))}
        for stamp, item in rows.get("MODE", []) if start <= stamp <= end
    ]
    rate_rows = [(stamp, item) for stamp, item in rows.get("RATE", []) if start <= stamp <= end]
    for axis, actual_key, desired_key, pid_kind, gyro_key in (
        ("roll", "R", "RDes", "PIDR", "GyrX"),
        ("pitch", "P", "PDes", "PIDP", "GyrY"),
        ("yaw", "Y", "YDes", None, "GyrZ"),
    ):
        paired = []
        for stamp, item in rate_rows:
            if not screen_start <= stamp <= screen_end:
                continue
            actual = finite_number(item.get(actual_key))
            desired = finite_number(item.get(desired_key))
            if actual is not None and desired is not None:
                paired.append((stamp, actual - desired))
        pid_errors = []
        if pid_kind:
            for stamp, item in rows.get(pid_kind, []):
                if not screen_start <= stamp <= screen_end:
                    continue
                value = finite_number(item.get("Err"))
                if value is not None:
                    pid_errors.append((stamp, value))
        samples = pid_errors if len(pid_errors) >= 64 else paired
        gyro_samples = []
        for stamp, item in rows.get("IMU", []):
            if not screen_start <= stamp <= screen_end or int(item.get("I", 0)) != 0:
                continue
            value = finite_number(item.get(gyro_key))
            if value is not None:
                gyro_samples.append((stamp, math.degrees(value)))
        result["control"][axis] = {
            "samples": len(paired),
            "error_rms_deg_s": rms(value for _, value in paired),
            "error_p95_abs_deg_s": percentile((abs(value) for _, value in paired), 0.95),
            "oscillation": spectrum(samples),
            "gyro_oscillation": spectrum(gyro_samples, high_hz=11.0),
        }

    clipping = 0
    high_vibration = False
    instances = sorted({int(item.get("IMU", 0)) for stamp, item in rows.get("VIBE", []) if screen_start <= stamp <= screen_end})
    for instance in instances:
        samples = [item for stamp, item in rows["VIBE"] if screen_start <= stamp <= screen_end and int(item.get("IMU", 0)) == instance]
        item_report = {}
        for key in ("VibeX", "VibeY", "VibeZ"):
            values = [finite_number(item.get(key)) for item in samples]
            values = [value for value in values if value is not None]
            if values:
                item_report[key] = {"median": float(statistics.median(values)), "max": max(values)}
                high_vibration |= max(values) > 60.0
        clips = [int(item.get("Clip", 0)) for item in samples]
        clip_delta = max(0, clips[-1] - clips[0]) if len(clips) >= 2 else 0
        clipping += clip_delta
        item_report["clip_increase"] = clip_delta
        result["vibration"][str(instance)] = item_report
    if clipping:
        result["blockers"].append(f"IMU clipping increased by {clipping}.")
    if high_vibration:
        result["blockers"].append("Vibration exceeded 60 m/s^2.")

    motor_rows = [item for stamp, item in rows.get("RCOU", []) if screen_start <= stamp <= screen_end]
    motor_fields = [f"C{i}" for i in range(1, 5) if any(f"C{i}" in item for item in motor_rows)]
    active_samples = 0
    saturated = 0
    for item in motor_rows:
        values = [finite_number(item.get(field)) for field in motor_fields]
        values = [value for value in values if value is not None]
        if values:
            active_samples += 1
            saturated += int(max(values) >= 1990)
    saturation_fraction = saturated / max(1, active_samples)
    result["motors"] = {
        "samples": active_samples,
        "saturation_samples": saturated,
        "saturation_fraction": saturation_fraction,
    }
    if saturation_fraction > 0.02:
        result["blockers"].append("Motor outputs were saturated for more than two percent of samples.")

    battery_rows = [item for stamp, item in rows.get("BAT", []) if start <= stamp <= end]
    currents = [finite_number(item.get("Curr")) for item in battery_rows]
    currents = [value for value in currents if value is not None and value >= 0]
    voltages = [finite_number(item.get("Volt")) for item in battery_rows]
    voltages = [value for value in voltages if value is not None and value > 0]
    result["power"] = {
        "current_median_a": float(statistics.median(currents)) if currents else None,
        "current_p95_a": percentile(currents, 0.95),
        "voltage_median_v": float(statistics.median(voltages)) if voltages else None,
    }
    result["errors"] = [item for stamp, item in rows.get("ERR", []) if interval[0] <= stamp <= interval[1]]
    for item in result["errors"]:
        subsystem = int(item.get("Subsys", -1))
        code = int(item.get("ECode", -1))
        if (subsystem, code) == (6, 1):
            result["blockers"].append("Battery failsafe triggered.")
        elif (subsystem, code) == (12, 1):
            result["blockers"].append("Crash check reported a ground impact.")
    keywords = ("failsafe", "crash", "ground mag anomaly", "rangefinder", "gps 1 still configuring")
    result["notable_messages"] = [
        str(item.get("Message"))
        for stamp, item in rows.get("MSG", [])
        if interval[0] <= stamp <= interval[1]
        and any(keyword in str(item.get("Message", "")).lower() for keyword in keywords)
    ]
    return result


def avoidance_health(
    rows: dict[str, list[tuple[float, dict[str, Any]]]],
    parameters: dict[str, float],
    interval: tuple[float, float],
) -> dict[str, Any]:
    start, end = screening_interval(interval)
    proximity_rows = [(stamp, item) for stamp, item in rows.get("PRX", []) if start <= stamp <= end]
    directions = {}
    for field in ("D0", "D90", "D270"):
        values = [finite_number(item.get(field)) for _, item in proximity_rows]
        values = [value for value in values if value is not None and value > 0]
        directions[field] = {
            "samples": len(values),
            "minimum_m": min(values) if values else None,
            "median_m": float(statistics.median(values)) if values else None,
        }
    downward = [
        finite_number(item.get("Dist"))
        for stamp, item in rows.get("RFND", [])
        if start <= stamp <= end and int(item.get("Orient", -1)) == 25
    ]
    downward = [value for value in downward if value is not None and value > 0]
    altitude_min = finite_number(parameters.get("PRX_ALT_MIN")) or 0.0
    below_fraction = (
        sum(value < altitude_min for value in downward) / len(downward)
        if downward and altitude_min > 0 else 0.0
    )
    option_channel = next(
        (channel for channel in range(1, 17) if int(parameters.get(f"RC{channel}_OPTION", 0)) == 40),
        None,
    )
    rc_values = []
    if option_channel:
        key = f"C{option_channel}"
        rc_values = [
            finite_number(item.get(key))
            for stamp, item in rows.get("RCIN", []) if start <= stamp <= end
        ]
        rc_values = [value for value in rc_values if value is not None]
    return {
        "proximity_message_samples": len(proximity_rows),
        "directions": directions,
        "avoid_enable": parameters.get("AVOID_ENABLE"),
        "avoid_behavior": parameters.get("AVOID_BEHAVE"),
        "avoid_margin_m": parameters.get("AVOID_MARGIN"),
        "proximity_altitude_min_m": altitude_min,
        "downward_height_samples": len(downward),
        "downward_height_median_m": float(statistics.median(downward)) if downward else None,
        "fraction_below_proximity_altitude_min": below_fraction,
        "switch_channel": option_channel,
        "switch_enabled_fraction": sum(value > 1700 for value in rc_values) / len(rc_values) if rc_values else None,
    }


def analyze_log(log_path: Path) -> dict[str, Any]:
    wanted = {"ARM", "MODE", "RATE", "PIDR", "PIDP", "RCOU", "VIBE", "IMU", "ATT", "CTUN", "RCIN", "ESC", "BAT", "BAT2", "RFND", "PRX", "DIST", "ERR", "EV", "MSG", "PARM"}
    rows: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
    parameters: dict[str, float] = {}
    message_counts: dict[str, int] = defaultdict(int)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        reader = DFReader_binary(str(log_path))
        while True:
            message = reader.recv_msg()
            if message is None:
                break
            kind = message.get_type()
            message_counts[kind] += 1
            if kind not in wanted:
                continue
            data = message.to_dict()
            if kind == "PARM" and data.get("Name"):
                value = finite_number(data.get("Value"))
                if value is not None:
                    parameters[str(data["Name"])] = value
            stamp_us = finite_number(data.get("TimeUS"))
            if stamp_us is not None:
                rows[kind].append((stamp_us / 1e6, data))

    intervals = armed_intervals(rows)
    flight = max(intervals, key=lambda pair: pair[1] - pair[0]) if intervals else None
    report: dict[str, Any] = {
        "schema": 1,
        "tool_version": VERSION,
        "created_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "log": str(log_path.resolve()),
        "log_sha256": sha256_file(log_path),
        "message_counts": dict(sorted(message_counts.items())),
        "parameter_count": len(parameters),
        "parameters_all": dict(sorted(parameters.items())),
        "parameters": {name: parameters.get(name) for name in sorted(PID_ALLOWLIST) if name in parameters},
        "status": "analyzed" if flight else "insufficient_data",
        "blockers": [],
        "warnings": [],
    }
    if not flight:
        report["blockers"].append("No armed interval was found in the log.")
        return report
    report["flight_intervals"] = [
        summarize_armed_interval(rows, interval, index)
        for index, interval in enumerate(intervals, start=1)
    ]
    screen_flight = screening_interval(flight)
    report["flight"] = {
        "start_s": flight[0],
        "end_s": flight[1],
        "duration_s": flight[1] - flight[0],
        "screening_start_s": screen_flight[0],
        "screening_end_s": screen_flight[1],
    }
    if flight[1] - flight[0] < MIN_AIRBORNE_SECONDS:
        report["blockers"].append("The armed interval is too short for a PID proposal.")

    rate_rows = [(stamp, item) for stamp, item in rows.get("RATE", []) if screen_flight[0] <= stamp <= screen_flight[1]]
    axes = {
        "roll": ("R", "RDes", "ROut"),
        "pitch": ("P", "PDes", "POut"),
        "yaw": ("Y", "YDes", "YOut"),
    }
    control = {}
    gyro_keys = {"roll": "GyrX", "pitch": "GyrY", "yaw": "GyrZ"}
    for axis, (actual_key, desired_key, output_key) in axes.items():
        paired = []
        outputs = []
        for stamp, item in rate_rows:
            actual = finite_number(item.get(actual_key))
            desired = finite_number(item.get(desired_key))
            output = finite_number(item.get(output_key))
            if actual is not None and desired is not None:
                paired.append((stamp, actual - desired))
            if output is not None:
                outputs.append(abs(output))
        errors = [value for _, value in paired]
        pid_kind = {"roll": "PIDR", "pitch": "PIDP"}.get(axis)
        pid_rows = [(stamp, item) for stamp, item in rows.get(pid_kind, []) if screen_flight[0] <= stamp <= screen_flight[1]] if pid_kind else []
        pid_errors = []
        pid_terms = {"P": [], "I": [], "D": []}
        for stamp, item in pid_rows:
            error = finite_number(item.get("Err"))
            if error is not None:
                pid_errors.append((stamp, error))
            for term in pid_terms:
                value = finite_number(item.get(term))
                if value is not None:
                    pid_terms[term].append(value)
        spectral_input = pid_errors if len(pid_errors) >= 64 else paired
        gyro_samples = []
        for stamp, item in rows.get("IMU", []):
            if not screen_flight[0] <= stamp <= screen_flight[1] or int(item.get("I", 0)) != 0:
                continue
            value = finite_number(item.get(gyro_keys[axis]))
            if value is not None:
                gyro_samples.append((stamp, math.degrees(value)))
        control[axis] = {
            "samples": len(errors),
            "pid_samples": len(pid_errors),
            "error_rms_deg_s": rms(errors),
            "error_p95_abs_deg_s": percentile((abs(v) for v in errors), 0.95),
            "controller_output_p95_abs": percentile(outputs, 0.95),
            "pid_term_rms": {term: rms(values) for term, values in pid_terms.items()},
            "oscillation": spectrum(spectral_input),
            "gyro_oscillation": spectrum(gyro_samples, high_hz=11.0),
        }
    report["control"] = control

    vibration = {}
    clipping = 0
    high_vibration = False
    instances = sorted({int(item.get("IMU", 0)) for stamp, item in rows.get("VIBE", []) if screen_flight[0] <= stamp <= screen_flight[1]})
    for instance in instances:
        samples = [item for stamp, item in rows["VIBE"] if screen_flight[0] <= stamp <= screen_flight[1] and int(item.get("IMU", 0)) == instance]
        item_report = {}
        for key in ("VibeX", "VibeY", "VibeZ"):
            values = [finite_number(item.get(key)) for item in samples]
            values = [value for value in values if value is not None]
            if values:
                item_report[key] = {"median": float(statistics.median(values)), "max": max(values)}
                high_vibration |= max(values) > 60.0
        clips = [int(item.get("Clip", 0)) for item in samples]
        clip_delta = max(0, clips[-1] - clips[0]) if len(clips) >= 2 else 0
        clipping += clip_delta
        item_report["clip_increase"] = clip_delta
        vibration[str(instance)] = item_report
    report["vibration"] = vibration
    if clipping:
        report["blockers"].append(f"IMU clipping increased by {clipping} during the flight.")
    if high_vibration:
        report["blockers"].append("Vibration exceeded the conservative 60 m/s^2 screening limit.")

    motor_rows = [item for stamp, item in rows.get("RCOU", []) if screen_flight[0] <= stamp <= screen_flight[1]]
    motor_fields = [f"C{i}" for i in range(1, 13) if any(f"C{i}" in item for item in motor_rows)]
    sat_samples = 0
    active_samples = 0
    for item in motor_rows:
        values = [finite_number(item.get(field)) for field in motor_fields[:4]]
        values = [value for value in values if value is not None]
        if values:
            active_samples += 1
            sat_samples += int(max(values) >= 1990)
    sat_fraction = sat_samples / max(1, active_samples)
    report["motors"] = {"samples": active_samples, "saturation_samples": sat_samples, "saturation_fraction": sat_fraction}
    if sat_fraction > 0.02:
        report["blockers"].append("Motor outputs were saturated for more than two percent of recorded samples.")

    report["rangefinders"] = rangefinder_health(rows, flight)
    for kind, item in report["rangefinders"].items():
        for field, health in item["fields"].items():
            if health["dropout_fraction"] > 0.1:
                report["warnings"].append(f"{kind}.{field} had more than ten percent invalid samples.")
    report["avoidance"] = avoidance_health(rows, parameters, flight)
    if report["avoidance"]["fraction_below_proximity_altitude_min"] > 0.5:
        report["warnings"].append(
            "Horizontal proximity was suppressed for most of the flight because height was below PRX_ALT_MIN."
        )
    report["errors"] = [item for stamp, item in rows.get("ERR", []) if flight[0] - 1 <= stamp <= flight[1] + 1]

    battery_rows = [item for stamp, item in rows.get("BAT", []) if flight[0] <= stamp <= flight[1]]
    currents = [finite_number(item.get("Curr")) for item in battery_rows]
    currents = [value for value in currents if value is not None and value >= 0]
    voltages = [finite_number(item.get("Volt")) for item in battery_rows]
    voltages = [value for value in voltages if value is not None and value > 0]
    throttle_rows = [item for stamp, item in rows.get("CTUN", []) if flight[0] <= stamp <= flight[1]]
    throttle = [finite_number(item.get("ThO")) for item in throttle_rows]
    throttle = [value for value in throttle if value is not None and value >= 0]
    esc_report = {}
    for instance in sorted({int(item.get("Instance", -1)) for stamp, item in rows.get("ESC", []) if flight[0] <= stamp <= flight[1]}):
        samples = [item for stamp, item in rows.get("ESC", []) if flight[0] <= stamp <= flight[1] and int(item.get("Instance", -1)) == instance]
        esc_currents = [finite_number(item.get("Curr")) for item in samples]
        esc_currents = [value for value in esc_currents if value is not None and value >= 0]
        esc_voltages = [finite_number(item.get("Volt")) for item in samples]
        esc_voltages = [value for value in esc_voltages if value is not None and value > 0]
        esc_temps = [finite_number(item.get("Temp")) for item in samples]
        esc_temps = [value for value in esc_temps if value is not None and value > 0]
        esc_errors = [finite_number(item.get("Err")) for item in samples]
        esc_errors = [value for value in esc_errors if value is not None]
        esc_report[str(instance)] = {
            "samples": len(samples),
            "current_median_a": float(statistics.median(esc_currents)) if esc_currents else None,
            "current_p95_a": percentile(esc_currents, 0.95),
            "voltage_median_v": float(statistics.median(esc_voltages)) if esc_voltages else None,
            "temperature_max_c": max(esc_temps) if esc_temps else None,
            "error_max": max(esc_errors) if esc_errors else None,
        }
    esc_current_median_sum = sum(
        item["current_median_a"] for item in esc_report.values() if item["current_median_a"] is not None
    )
    report["power"] = {
        "current_samples": len(currents),
        "current_median_a": float(statistics.median(currents)) if currents else None,
        "current_p95_a": percentile(currents, 0.95),
        "voltage_median_v": float(statistics.median(voltages)) if voltages else None,
        "throttle_output_median": float(statistics.median(throttle)) if throttle else None,
        "escs": esc_report,
        "esc_current_median_sum_a": esc_current_median_sum if len(esc_report) >= 4 else None,
        "quality": "usable" if (
            (len(currents) >= 50 and len(voltages) >= 50 and len(throttle) >= 50)
            or (len(esc_report) >= 4 and all(item["samples"] >= 50 for item in esc_report.values()))
        ) else "insufficient",
    }
    if any((item.get("error_max") or 0) > 0 for item in esc_report.values()):
        report["warnings"].append("One or more ESC telemetry streams reported a non-zero error count.")
    if len(report["flight_intervals"]) > 1:
        longest_index = max(
            range(len(report["flight_intervals"])),
            key=lambda item: report["flight_intervals"][item]["duration_s"],
        )
        for interval_report in report["flight_intervals"]:
            if interval_report["index"] - 1 == longest_index:
                continue
            for blocker in interval_report["blockers"]:
                tagged = f"Flight interval {interval_report['index']}: {blocker}"
                if tagged not in report["blockers"]:
                    report["blockers"].append(tagged)
    report["notable_messages"] = sorted({
        message
        for interval_report in report["flight_intervals"]
        for message in interval_report.get("notable_messages", [])
    })
    if any("ground mag anomaly" in message.lower() for message in report["notable_messages"]):
        report["warnings"].append("The estimator re-aligned yaw after detecting a magnetic anomaly while on the ground.")
    if any("gps 1 still configuring" in message.lower() for message in report["notable_messages"]):
        report["warnings"].append("GPS reported that configuration was still in progress during at least one arming interval.")
    return report


def make_proposal(report: dict[str, Any]) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "schema": 1,
        "tool_version": VERSION,
        "created_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_log": report.get("log"),
        "source_log_sha256": report.get("log_sha256"),
        "status": "blocked" if report.get("blockers") else "review_required",
        "blockers": list(report.get("blockers", [])),
        "changes": [],
        "policy": {
            "armed_writes": False,
            "automatic_writes": False,
            "maximum_single_change_fraction": MAX_SINGLE_CHANGE_FRACTION,
            "allowlist": sorted(PID_ALLOWLIST),
        },
    }
    if proposal["blockers"]:
        proposal["decision"] = "Resolve blockers and collect another short hover log. No PID changes proposed."
    else:
        params = report.get("parameters", {})
        for axis, code in (("roll", "RLL"), ("pitch", "PIT")):
            axis_report = report.get("control", {}).get(axis, {})
            osc = axis_report.get("oscillation", {})
            source = "control error"
            if not osc.get("usable"):
                osc = axis_report.get("gyro_oscillation", {})
                source = "measured gyro response"
            error_rms = axis_report.get("error_rms_deg_s", 0.0)
            if not osc.get("usable"):
                continue
            if 4.0 <= osc.get("peak_hz", 0.0) <= 20.0 and osc.get("peak_to_median_ratio", 0.0) >= 6.0 and error_rms >= 5.0:
                # Preserve the axis gain relationship by moving P, I, and D
                # together.  Larger or upward steps are never generated here.
                for suffix, reduction in (("P", 0.10), ("I", 0.10), ("D", 0.10)):
                    name = f"ATC_RAT_{code}_{suffix}"
                    current = finite_number(params.get(name))
                    if current is None or current <= 0:
                        continue
                    target = current * (1.0 - reduction)
                    proposal["changes"].append({
                        "name": name,
                        "before": current,
                        "target": target,
                        "fraction": -reduction,
                        "reason": f"{axis} {source} has a strong {osc['peak_hz']:.1f} Hz peak",
                    })
        if proposal["changes"]:
            proposal["decision"] = "Conservative gain reductions are ready for explicit review and a disarmed apply step."
        else:
            proposal["status"] = "no_change"
            proposal["decision"] = "The evidence did not meet the threshold for a guarded PID reduction."
    proposal["choices"] = {
        "best_choice": {
            "priority": "stability, control margin, sensor reliability, and recoverability",
            "recommendation": proposal["decision"],
            "eligible_for_guarded_apply": proposal["status"] == "review_required",
        },
        "most_efficient": {
            "priority": "lower current draw, balanced motor loading, and flight time",
            "recommendation": (
                "Efficiency optimization is deferred until every safety gate passes."
                if report.get("blockers") else
                "Power data is insufficient for a trustworthy efficiency recommendation."
                if report.get("power", {}).get("quality") != "usable" else
                "Use current draw, hover throttle, motor balance, propeller choice, and weight for efficiency; do not raise PID gains for efficiency."
            ),
            "power_data_quality": report.get("power", {}).get("quality", "insufficient"),
            "eligible_for_guarded_apply": False,
        },
    }
    token_source = json.dumps({"source": proposal.get("source_log_sha256"), "changes": proposal["changes"]}, sort_keys=True).encode()
    proposal["confirmation_token"] = hashlib.sha256(token_source).hexdigest()[:10].upper()
    return proposal


def ollama_model_status(endpoint: str, model: str, timeout: float = 5.0) -> dict[str, Any]:
    """Check the local Ollama service and selected model without running inference."""
    request = urllib.request.Request(endpoint.rstrip("/") + "/api/tags", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode())
        models = sorted(
            str(item.get("name", "")).strip()
            for item in parsed.get("models", [])
            if str(item.get("name", "")).strip()
        )
        installed = model in models
        if model == "qwen2.5:3b":
            ready_message = f"Connected to local Ollama; {model} is installed and ready (balanced default, about 33 seconds in the local advisory benchmark)."
        elif model == "gemma4:26b":
            ready_message = f"Connected to local Ollama; {model} is installed, but the local benchmark exceeded six minutes. Deterministic fallback may be used."
        else:
            ready_message = f"Connected to local Ollama; {model} is installed and ready."
        return {
            "available": True,
            "model": model,
            "model_installed": installed,
            "models": models,
            "message": (
                ready_message
                if installed else
                f"Connected to local Ollama, but {model} is not installed. Deterministic fallback will be used."
            ),
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as error:
        return {
            "available": False,
            "model": model,
            "model_installed": False,
            "models": [],
            "message": f"Local Ollama unavailable ({error}). Deterministic fallback will be used.",
        }


def advisory_consistency_issue(explanation: str, proposal: dict[str, Any]) -> str | None:
    """Reject prose that contradicts or expands the deterministic proposal."""
    lowered = explanation.lower()
    command_phrases = (
        "arm the", "flash the", "upload firmware", "write the parameter",
        "set the parameter", "change the serial", "disable the failsafe",
    )
    if any(phrase in lowered for phrase in command_phrases):
        return "model text contained a controller-action instruction"
    changes = proposal.get("changes", [])
    reductions = [
        item for item in changes
        if finite_number(item.get("target")) is not None
        and finite_number(item.get("before")) is not None
        and float(item["target"]) < float(item["before"])
    ]
    if reductions:
        contradictory = (
            "increase the gain", "increase gains", "increase in gain", "raise the gain",
            "raise gains", "higher gain", "above the current", "turn up the gain",
        )
        if any(phrase in lowered for phrase in contradictory):
            return "model text contradicted the guarded gain reduction"
        if "reduc" not in lowered:
            return "model text omitted the guarded gain reduction"
    return None


def ollama_explanation_result(report: dict[str, Any], proposal: dict[str, Any], model: str, endpoint: str) -> dict[str, Any]:
    """Return advisory prose plus provenance; never returns controller actions."""
    # Blocked reports are safety-critical.  Explain those from verified fields
    # only; the model is reserved for reports that already passed every gate.
    if report.get("blockers"):
        return {
            "text": deterministic_explanation(report, proposal, "Because this report is blocked, its explanation was generated from verified fields without model interpretation."),
            "source": "deterministic",
            "model": model,
            "status": "skipped_blocked_report",
            "message": "Model interpretation skipped because deterministic safety blockers are present.",
        }
    safe_payload = {
        "flight": report.get("flight"),
        "control": report.get("control"),
        "vibration": report.get("vibration"),
        "motors": report.get("motors"),
        "rangefinders": report.get("rangefinders"),
        "blockers": report.get("blockers"),
        "warnings": report.get("warnings"),
        "proposal": {key: proposal.get(key) for key in ("status", "decision", "changes")},
    }
    prompt = (
        "Explain this ArduPilot flight analysis in plain language. The deterministic report is authoritative. "
        "If blockers are present, explicitly say the flight is blocked from tuning and never call it safe, smooth, "
        "normal, or issue-free. Mention every blocker. Do not invent measurements, attribute a decision to a team, "
        "propose parameters beyond those already listed, or give commands. Separate verified findings, limits, and "
        "the next safe test. Never recommend increasing or raising gains. If the proposal lists reductions, only "
        "describe those exact reductions. The next test is a physical inspection followed by a brief low-altitude "
        "hover and review of the new log. Keep the response under 140 words.\n\n" + json.dumps(safe_payload, separators=(",", ":"))
    )
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 170},
    }).encode()
    request = urllib.request.Request(endpoint.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            parsed = json.loads(response.read().decode())
        explanation = str(parsed.get("response", "")).strip()
        issue = advisory_consistency_issue(explanation, proposal) if explanation else None
        if issue:
            message = f"Local-model prose failed safety consistency checks ({issue}) and was discarded; deterministic fallback was used."
            return {
                "text": deterministic_explanation(report, proposal, message),
                "source": "deterministic",
                "model": model,
                "status": "rejected_inconsistent",
                "message": message,
            }
        if explanation:
            return {
                "text": explanation,
                "source": "ollama",
                "model": model,
                "status": "ok",
                "message": f"Advisory explanation generated locally by {model}.",
            }
        return {
            "text": deterministic_explanation(report, proposal, "Local model returned no explanation; deterministic fallback was used."),
            "source": "deterministic",
            "model": model,
            "status": "empty_response",
            "message": "Local model returned no explanation; deterministic fallback was used.",
        }
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as error:
        message = f"Local model unavailable ({error}); deterministic fallback was used."
        return {
            "text": deterministic_explanation(report, proposal, message),
            "source": "deterministic",
            "model": model,
            "status": "unavailable",
            "message": message,
        }


def ollama_explanation(report: dict[str, Any], proposal: dict[str, Any], model: str, endpoint: str) -> str:
    """Compatibility wrapper used by the CLI and batch analyzer."""
    return ollama_explanation_result(report, proposal, model, endpoint)["text"]


def deterministic_explanation(report: dict[str, Any], proposal: dict[str, Any], note: str | None = None) -> str:
    lines = []
    if note:
        lines.append(note)
    if report.get("blockers"):
        lines.append("This flight is blocked from PID tuning. The verified blockers are:")
        lines.extend(f"- {item}" for item in report["blockers"])
    else:
        lines.append("The deterministic safety gates passed for this report.")
    lines.append("Best choice: " + proposal.get("choices", {}).get("best_choice", {}).get("recommendation", proposal.get("decision", "No recommendation.")))
    lines.append("Most efficient: " + proposal.get("choices", {}).get("most_efficient", {}).get("recommendation", "No efficiency recommendation."))
    lines.append("The laptop remains read-only while airborne; any eligible change requires landing, disarm verification, a full backup, and read-back verification.")
    return "\n\n".join(lines)


def write_outputs(report: dict[str, Any], proposal: dict[str, Any], output_dir: Path, explanation: str | None = None) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"analysis-{stamp}.json"
    proposal_path = output_dir / f"proposal-{stamp}.json"
    summary_path = output_dir / f"summary-{stamp}.md"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    lines = [
        "# Flight safety analysis", "", f"- Status: **{proposal['status']}**",
        f"- Decision: {proposal['decision']}", "",
    ]
    if report.get("blockers"):
        lines += ["## Blockers", ""] + [f"- {item}" for item in report["blockers"]] + [""]
    if report.get("warnings"):
        lines += ["## Warnings", ""] + [f"- {item}" for item in report["warnings"]] + [""]
    avoidance = report.get("avoidance", {})
    if avoidance:
        lines += [
            "## Obstacle avoidance", "",
            f"- Proximity samples: {avoidance.get('proximity_message_samples', 0)}",
            f"- Avoidance switch channel: {avoidance.get('switch_channel')}",
            f"- Proximity minimum altitude: {avoidance.get('proximity_altitude_min_m')} m",
            f"- Time below that minimum: {100.0 * avoidance.get('fraction_below_proximity_altitude_min', 0.0):.1f}%",
            "",
        ]
    lines += ["## Proposed changes", ""]
    if proposal["changes"]:
        lines += ["| Parameter | Current | Proposed | Reason |", "|---|---:|---:|---|"]
        lines += [f"| `{item['name']}` | {item['before']:.8g} | {item['target']:.8g} | {item['reason']} |" for item in proposal["changes"]]
    else:
        lines.append("No parameter changes were proposed.")
    choices = proposal.get("choices", {})
    if choices:
        lines += ["", "## Choice comparison", "", "- **Best choice:** " + choices.get("best_choice", {}).get("recommendation", "Unavailable"), "- **Most efficient:** " + choices.get("most_efficient", {}).get("recommendation", "Unavailable")]
    lines += ["", "## Guardrails", "", "- The live monitor is read-only.", "- Applying a proposal is blocked while armed.", "- Only six roll/pitch rate PID parameters are writable.", "- Each change is reduction-only and capped at 10 percent.", "- A full parameter backup and read-back verification are mandatory.", "- USB, serial, frame, motor-layout, filter, rangefinder, avoidance, and failsafe settings are protected."]
    if explanation:
        lines += ["", "## Local model explanation", "", explanation]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"analysis": str(report_path), "proposal": str(proposal_path), "summary": str(summary_path)}


def batch_analyze(log_paths: list[Path], output_dir: Path, llm_model: str | None = None, ollama_url: str = "http://127.0.0.1:11434") -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for log_path in sorted(log_paths, key=lambda item: item.name.lower()):
        report = analyze_log(log_path)
        proposal = make_proposal(report)
        explanation = ollama_explanation(report, proposal, llm_model, ollama_url) if llm_model else None
        paths = write_outputs(report, proposal, output_dir, explanation)
        records.append({"log": str(log_path.resolve()), "report": report, "proposal": proposal, "outputs": paths})
    pid_prefixes = ("ATC_RAT_", "ATC_ANG_", "PSC_", "LOIT_", "INS_GYRO", "INS_HNTCH")
    all_names = sorted({name for record in records for name in record["report"].get("parameters_all", {}) if name.startswith(pid_prefixes)})
    parameter_matrix = {
        name: {Path(record["log"]).name: record["report"].get("parameters_all", {}).get(name) for record in records}
        for name in all_names
    }
    aggregate = {
        "schema": 1,
        "tool_version": VERSION,
        "created_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "log_count": len(records),
        "logs": [
            {
                "name": Path(record["log"]).name,
                "sha256": record["report"].get("log_sha256"),
                "flight": record["report"].get("flight"),
                "flight_intervals": record["report"].get("flight_intervals"),
                "blockers": record["report"].get("blockers"),
                "warnings": record["report"].get("warnings"),
                "control": record["report"].get("control"),
                "vibration": record["report"].get("vibration"),
                "motors": record["report"].get("motors"),
                "power": record["report"].get("power"),
                "rangefinders": record["report"].get("rangefinders"),
                "avoidance": record["report"].get("avoidance"),
                "proposal_status": record["proposal"].get("status"),
                "best_choice": record["proposal"].get("choices", {}).get("best_choice"),
                "most_efficient": record["proposal"].get("choices", {}).get("most_efficient"),
            }
            for record in records
        ],
        "pid_and_filter_parameter_matrix": parameter_matrix,
        "rule": "No combined tune is eligible unless every selected flight passes the safety gates and uses a consistent parameter baseline.",
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"batch-analysis-{stamp}.json"
    path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    return path


@dataclass
class Link:
    connection: Any
    system: int
    component: int
    last_heartbeat: Any
    last_gcs_heartbeat: float = 0.0

    def receive(self, timeout: float = 0.2):
        now = time.monotonic()
        if now - self.last_gcs_heartbeat > 1.0:
            self.connection.mav.heartbeat_send(6, 8, 0, 0, 0)
            self.last_gcs_heartbeat = now
        message = self.connection.recv_match(blocking=True, timeout=timeout)
        if not message or (message.get_srcSystem(), message.get_srcComponent()) != (self.system, self.component):
            return None
        if message.get_type() == "HEARTBEAT":
            self.last_heartbeat = message
        return message

    def require_disarmed(self, fresh_seconds: float = 4.0):
        end = time.monotonic() + fresh_seconds
        while time.monotonic() < end:
            message = self.receive(0.25)
            if message and message.get_type() == "HEARTBEAT":
                if message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                    raise RuntimeError("Controller is armed; writes are blocked")
                return
        raise RuntimeError("No fresh disarmed heartbeat")


def connect(port: str, baud: int) -> Link:
    connection = mavutil.mavlink_connection(port, baud=baud, source_system=255, source_component=190, autoreconnect=False)
    connection.port.timeout = 0
    connection.port.write_timeout = 2
    heartbeat = connection.wait_heartbeat(timeout=12)
    if not heartbeat or heartbeat.autopilot != 3 or heartbeat.get_srcComponent() != 1:
        connection.close()
        raise RuntimeError("No ArduPilot flight-controller heartbeat")
    return Link(connection, heartbeat.get_srcSystem(), heartbeat.get_srcComponent(), heartbeat)


def read_parameter(link: Link, name: str, typed: bool = False):
    link.connection.mav.param_request_read_send(link.system, link.component, name.encode(), -1)
    end = time.monotonic() + 4.0
    while time.monotonic() < end:
        message = link.receive()
        if message and message.get_type() == "PARAM_VALUE" and message.param_id == name:
            result = {"value": float(message.param_value), "type": int(message.param_type)}
            return result if typed else result["value"]
    raise RuntimeError(f"Parameter read timed out: {name}")


def read_all_parameters(link: Link) -> dict[str, dict[str, Any]]:
    parameters: dict[str, dict[str, Any]] = {}
    indices = set()
    expected = None
    link.connection.mav.param_request_list_send(link.system, link.component)
    end = time.monotonic() + 60.0
    while time.monotonic() < end:
        message = link.receive()
        if not message or message.get_type() != "PARAM_VALUE":
            continue
        parameters[message.param_id] = {"value": float(message.param_value), "type": int(message.param_type)}
        indices.add(int(message.param_index))
        expected = int(message.param_count)
        if expected and len(indices) >= expected:
            return parameters
    raise RuntimeError(f"Incomplete parameter backup: received {len(indices)} of {expected}")


def write_parameter(link: Link, name: str, value: float, param_type: int):
    link.require_disarmed()
    link.connection.mav.param_set_send(link.system, link.component, name.encode(), float(value), param_type)
    end = time.monotonic() + 5.0
    acknowledged = False
    while time.monotonic() < end:
        message = link.receive()
        if message and message.get_type() == "PARAM_VALUE" and message.param_id == name:
            if math.isclose(float(message.param_value), value, rel_tol=0.0, abs_tol=1e-6):
                acknowledged = True
                break
    if not acknowledged:
        raise RuntimeError(f"No write acknowledgement for {name}")
    readback = read_parameter(link, name)
    if not math.isclose(readback, value, rel_tol=0.0, abs_tol=1e-6):
        raise RuntimeError(f"Read-back mismatch for {name}")


def validate_proposal(proposal: dict[str, Any], confirmation: str):
    if proposal.get("confirmation_token") != confirmation:
        raise RuntimeError("Confirmation token does not match the proposal")
    if proposal.get("status") != "review_required" or not proposal.get("changes"):
        raise RuntimeError("Proposal is not eligible for application")
    for item in proposal["changes"]:
        name = item.get("name")
        before = finite_number(item.get("before"))
        target = finite_number(item.get("target"))
        if name not in PID_ALLOWLIST or before is None or target is None or before <= 0 or target <= 0:
            raise RuntimeError(f"Unsafe or invalid proposal entry: {name}")
        fraction = abs(target / before - 1.0)
        if fraction > MAX_SINGLE_CHANGE_FRACTION + 1e-9 or target > before:
            raise RuntimeError(f"Proposal exceeds reduction-only limit: {name}")
        low, high = PARAMETER_BOUNDS[name]
        if not low <= target <= high:
            raise RuntimeError(f"Proposal exceeds absolute safety bounds: {name}")


def capture_baseline(port: str, baud: int, output_dir: Path) -> Path:
    """Capture every controller parameter while disarmed for drift checks."""
    output_dir.mkdir(parents=True, exist_ok=True)
    link = connect(port, baud)
    try:
        link.require_disarmed()
        parameters = read_all_parameters(link)
        link.require_disarmed()
        profile = {
            "schema": 1,
            "tool_version": VERSION,
            "created_local": datetime.now().astimezone().isoformat(timespec="seconds"),
            "vehicle": "ArduCopter / MicoAir H743 V2",
            "parameter_count": len(parameters),
            "parameters": parameters,
            "policy": {
                "writable_parameters": sorted(PID_ALLOWLIST),
                "maximum_reduction_fraction_per_completed_flight": MAX_SINGLE_CHANGE_FRACTION,
                "increases_allowed": False,
                "writes_while_armed": False,
                "live_flight_writes": False,
            },
        }
        path = output_dir / "aircraft-baseline.json"
        path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        return path
    finally:
        link.connection.close()


def compare_baseline(current: dict[str, dict[str, Any]], baseline_path: Path, allowed_changes: set[str] | None = None) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    expected = baseline.get("parameters", {})
    allowed_changes = allowed_changes or set()
    result = {"configuration_changes": {}, "calibration_drift": {}, "volatile_changes": {}, "added": [], "missing": []}
    for name in sorted(set(expected).intersection(current)):
        before = finite_number(expected[name].get("value"))
        after = finite_number(current[name].get("value"))
        if before is None or after is None or math.isclose(before, after, rel_tol=0.0, abs_tol=1e-6) or name in allowed_changes:
            continue
        item = {"baseline": before, "current": after}
        if name in AUTO_CHANGING or name.startswith("STAT_"):
            result["volatile_changes"][name] = item
        elif name.startswith(CALIBRATION_PREFIXES):
            result["calibration_drift"][name] = item
        else:
            result["configuration_changes"][name] = item
    result["added"] = sorted(set(current) - set(expected))
    result["missing"] = sorted(set(expected) - set(current))
    return result


def apply_proposal(path: Path, port: str, baud: int, confirmation: str, output_dir: Path, baseline_path: Path | None = None) -> Path:
    proposal = json.loads(path.read_text(encoding="utf-8"))
    validate_proposal(proposal, confirmation)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = output_dir / f"apply-audit-{stamp}.json"
    audit: dict[str, Any] = {"status": "starting", "proposal": str(path.resolve()), "changed": []}
    link = connect(port, baud)
    before: dict[str, dict[str, Any]] = {}
    try:
        link.require_disarmed()
        before = read_all_parameters(link)
        if baseline_path:
            baseline_diff = compare_baseline(before, baseline_path, {item["name"] for item in proposal["changes"]})
            audit["baseline_diff_before"] = baseline_diff
            if baseline_diff["configuration_changes"] or baseline_diff["added"] or baseline_diff["missing"]:
                raise RuntimeError("Full-parameter baseline drift detected; review the audit before applying PID changes")
        for item in proposal["changes"]:
            name = item["name"]
            if name not in before:
                before[name] = read_parameter(link, name, typed=True)
            if not math.isclose(before[name]["value"], float(item["before"]), rel_tol=0.0, abs_tol=1e-6):
                raise RuntimeError(f"Controller value changed since analysis: {name}")
        backup_path = output_dir / f"parameters-before-{stamp}.param"
        backup_path.write_text("".join(f"{name}\t{item['value']:.12g}\n" for name, item in sorted(before.items())), encoding="utf-8")
        audit.update(status="backed_up", backup=str(backup_path))
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        for item in proposal["changes"]:
            name = item["name"]
            write_parameter(link, name, float(item["target"]), int(before[name]["type"]))
            audit["changed"].append(name)
            audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        after = read_all_parameters(link)
        for item in proposal["changes"]:
            if not math.isclose(after[item["name"]]["value"], float(item["target"]), rel_tol=0.0, abs_tol=1e-6):
                raise RuntimeError(f"Final verification failed: {item['name']}")
        protected_changes = {
            name: {"before": item["value"], "after": after[name]["value"]}
            for name, item in before.items()
            if name in after and is_protected(name) and not math.isclose(item["value"], after[name]["value"], rel_tol=0.0, abs_tol=1e-6)
        }
        unexpected = {
            name: {"before": item["value"], "after": after[name]["value"]}
            for name, item in before.items()
            if name in after and name not in PID_ALLOWLIST and name not in AUTO_CHANGING
            and not math.isclose(item["value"], after[name]["value"], rel_tol=0.0, abs_tol=1e-6)
        }
        if protected_changes or unexpected:
            raise RuntimeError(f"Unrelated parameter change detected: {protected_changes or unexpected}")
        audit.update(status="verified", protected_changes={}, unexpected_changes={})
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        return audit_path
    except Exception as error:
        audit.update(status="failed", error=str(error))
        if before and audit["changed"]:
            rollback = {}
            for name in reversed(audit["changed"]):
                try:
                    write_parameter(link, name, before[name]["value"], int(before[name]["type"]))
                    rollback[name] = "restored"
                except Exception as rollback_error:
                    rollback[name] = f"FAILED: {rollback_error}"
                    break
            audit["rollback"] = rollback
        audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
        raise
    finally:
        link.connection.close()


def live_monitor(port: str, baud: int, seconds: float, output_dir: Path, stop_event=None, on_event=None):
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"live-{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    link = connect(port, baud)
    link.connection.mav.heartbeat_send(6, 8, 0, 0, 0)
    link.last_gcs_heartbeat = time.monotonic()
    # Ask ArduPilot to stream telemetry to this read-only GCS connection. This
    # changes no parameter and is not persisted by the controller.
    link.connection.mav.request_data_stream_send(
        link.system,
        link.component,
        mavutil.mavlink.MAV_DATA_STREAM_ALL,
        5,
        1,
    )
    started = time.monotonic()
    last_state = None
    last_request = 0.0
    requested_ids = (
        mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_VIBRATION,
        mavutil.mavlink.MAVLINK_MSG_ID_RANGEFINDER,
        mavutil.mavlink.MAVLINK_MSG_ID_DISTANCE_SENSOR,
        mavutil.mavlink.MAVLINK_MSG_ID_BATTERY_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_EKF_STATUS_REPORT,
    )
    try:
        with path.open("w", encoding="utf-8") as handle:
            initial = {
                "elapsed_s": 0.0,
                "type": "HEARTBEAT",
                "data": link.last_heartbeat.to_dict(),
            }
            handle.write(json.dumps(initial, default=str) + "\n")
            handle.flush()
            if on_event:
                on_event(initial)
            while time.monotonic() - started < seconds and not (stop_event and stop_event.is_set()):
                now = time.monotonic()
                if now - last_request >= 1.0:
                    for message_id in requested_ids:
                        link.connection.mav.command_long_send(
                            link.system,
                            link.component,
                            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE,
                            0,
                            message_id,
                            0,
                            0,
                            0,
                            0,
                            0,
                            0,
                        )
                    last_request = now
                message = link.receive(0.25)
                if not message:
                    continue
                kind = message.get_type()
                if kind not in {"HEARTBEAT", "VIBRATION", "RANGEFINDER", "DISTANCE_SENSOR", "SYS_STATUS", "BATTERY_STATUS", "RC_CHANNELS", "GPS_RAW_INT", "EKF_STATUS_REPORT", "STATUSTEXT"}:
                    continue
                item = {"elapsed_s": round(time.monotonic() - started, 3), "type": kind, "data": message.to_dict()}
                handle.write(json.dumps(item, default=str) + "\n")
                handle.flush()
                if on_event:
                    on_event(item)
                if kind == "HEARTBEAT":
                    state = "armed" if message.base_mode & 128 else "disarmed"
                    if state != last_state:
                        print(f"STATE {state}", flush=True)
                        last_state = state
                elif kind == "STATUSTEXT":
                    print(f"STATUS {message.text}", flush=True)
    finally:
        link.connection.close()
    print(path)
    return path


def cmd_analyze(args):
    report = analyze_log(Path(args.log))
    proposal = make_proposal(report)
    explanation = None
    if args.llm_model:
        explanation = ollama_explanation(report, proposal, args.llm_model, args.ollama_url)
    paths = write_outputs(report, proposal, Path(args.output), explanation)
    print(json.dumps({"status": proposal["status"], "decision": proposal["decision"], "paths": paths, "confirmation_token": proposal["confirmation_token"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Analyze a DataFlash BIN and create a guarded proposal")
    analyze.add_argument("--log", required=True)
    analyze.add_argument("--output", default=str(DEFAULT_OUTPUT))
    analyze.add_argument("--llm-model", help="Optional local Ollama model name used only for explanation")
    analyze.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    analyze.set_defaults(func=cmd_analyze)
    live = sub.add_parser("monitor", help="Record read-only live health telemetry")
    live.add_argument("--port", default="COM8")
    live.add_argument("--baud", type=int, default=115200)
    live.add_argument("--seconds", type=float, default=60.0)
    live.add_argument("--output", default=str(DEFAULT_OUTPUT))
    live.set_defaults(func=lambda args: live_monitor(args.port, args.baud, args.seconds, Path(args.output)))
    apply = sub.add_parser("apply", help="Apply an eligible proposal with backup, disarm checks, and rollback")
    apply.add_argument("--proposal", required=True)
    apply.add_argument("--confirm", required=True)
    apply.add_argument("--port", default="COM8")
    apply.add_argument("--baud", type=int, default=115200)
    apply.add_argument("--output", default=str(DEFAULT_OUTPUT))
    apply.add_argument("--baseline", help="Optional full-controller baseline JSON")
    apply.set_defaults(func=lambda args: print(apply_proposal(Path(args.proposal), args.port, args.baud, args.confirm, Path(args.output), Path(args.baseline) if args.baseline else None)))
    baseline = sub.add_parser("baseline", help="Capture every controller parameter while disarmed")
    baseline.add_argument("--port", default="COM8")
    baseline.add_argument("--baud", type=int, default=115200)
    baseline.add_argument("--output", default=str(DEFAULT_OUTPUT))
    baseline.set_defaults(func=lambda args: print(capture_baseline(args.port, args.baud, Path(args.output))))
    batch = sub.add_parser("batch", help="Analyze several DataFlash BIN files and compare their full PID/filter sets")
    batch.add_argument("logs", nargs="+")
    batch.add_argument("--output", default=str(DEFAULT_OUTPUT))
    batch.add_argument("--llm-model")
    batch.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    batch.set_defaults(func=lambda args: print(batch_analyze([Path(item) for item in args.logs], Path(args.output), args.llm_model, args.ollama_url)))
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
