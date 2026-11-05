"""Monte-Carlo architecture screen for hover-time PID writes.

This is deliberately a simplified uncertain roll-axis model, not an aircraft
qualification simulation.  It compares a fixed conservative controller with a
laptop supervisor that may reduce gains after delayed/noisy oscillation
detection.  The purpose is to screen architecture risk, not predict the exact
vehicle.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


SEED = 74302
TRIALS = 250
DT = 0.01
DURATION = 8.0


def trial(rng: np.random.Generator, adaptive: bool):
    inertia = rng.uniform(0.65, 1.55)
    damping = rng.uniform(0.16, 0.55)
    actuator_delay = rng.integers(5, 40)
    telemetry_delay = rng.integers(75, 400)
    dropout = rng.uniform(0.0, 0.12)
    noise = rng.uniform(0.002, 0.018)
    disturbance = rng.uniform(0.02, 0.12)
    kp, ki, kd = 4.8, 0.9, 1.45
    angle = rate = integral = 0.0
    target = math.radians(4.0)
    command_queue = [0.0] * int(actuator_delay)
    telemetry = []
    errors = []
    rates = []
    updates = 0
    next_check = 1.5
    for index in range(int(DURATION / DT)):
        t = index * DT
        if 3.0 < t < 3.35:
            external = disturbance
        else:
            external = 0.0
        measured = angle + rng.normal(0.0, noise)
        error = target - measured
        integral = float(np.clip(integral + error * DT, -0.35, 0.35))
        command = float(np.clip(kp * error + ki * integral - kd * rate, -1.0, 1.0))
        command_queue.append(command)
        applied = command_queue.pop(0)
        rate += ((applied + external) / inertia - damping * rate) * DT
        angle += rate * DT
        errors.append(error)
        rates.append(rate)
        if rng.random() >= dropout:
            telemetry.append((t, error, rate))
        if adaptive and t >= next_check and updates < 3:
            cutoff = t - telemetry_delay * DT
            window = [sample for sample in telemetry if cutoff - 0.8 <= sample[0] <= cutoff]
            if len(window) > 40:
                err_rms = math.sqrt(sum(sample[1] ** 2 for sample in window) / len(window))
                rate_rms = math.sqrt(sum(sample[2] ** 2 for sample in window) / len(window))
                # A noisy supervisor can false-trigger; this models the decision
                # boundary rather than granting perfect plant knowledge.
                detected = rate_rms > 0.025 and err_rms > 0.006
                false_trigger = rng.random() < 0.025 + dropout * 0.2
                if detected or false_trigger:
                    kp *= 0.9
                    ki *= 0.9
                    kd *= 0.9
                    updates += 1
            next_check += 1.0
    abs_errors = np.abs(np.asarray(errors))
    abs_rates = np.abs(np.asarray(rates))
    tail = abs_errors[int(5.0 / DT):]
    return {
        "peak_angle_error_deg": float(np.degrees(abs_errors.max())),
        "tail_rms_angle_error_deg": float(np.degrees(np.sqrt(np.mean(tail * tail)))),
        "peak_rate_deg_s": float(np.degrees(abs_rates.max())),
        "updates": updates,
        "unsafe": bool(np.degrees(abs_errors.max()) > 18.0 or np.degrees(abs_rates.max()) > 140.0),
    }


def summarize(rows):
    result = {"trials": len(rows), "unsafe_trials": sum(item["unsafe"] for item in rows)}
    for key in ("peak_angle_error_deg", "tail_rms_angle_error_deg", "peak_rate_deg_s", "updates"):
        values = np.asarray([item[key] for item in rows], dtype=float)
        result[key] = {"median": float(np.median(values)), "p95": float(np.percentile(values, 95)), "max": float(values.max())}
    return result


def main():
    rng = np.random.default_rng(SEED)
    parameters = [rng.integers(0, 2**63 - 1) for _ in range(TRIALS)]
    fixed = [trial(np.random.default_rng(seed), False) for seed in parameters]
    adaptive = [trial(np.random.default_rng(seed), True) for seed in parameters]
    result = {
        "model": "simplified uncertain roll-axis architecture screen",
        "seed": SEED,
        "trials": TRIALS,
        "fixed_conservative": summarize(fixed),
        "delayed_live_gain_reducer": summarize(adaptive),
        "decision": "Keep the laptop monitor read-only in flight. Use it for alerts and post-landing proposals; leave real-time stabilization, notch tracking, and failsafes on ArduPilot.",
        "limits": [
            "This is not a validated model of the user's aircraft.",
            "It screens the architecture under uncertainty; it does not certify flight safety.",
            "Real sensor faults, mode transitions, propulsion faults, and ground effect are more complex.",
        ],
    }
    out = Path(__file__).resolve().parents[1] / "outputs" / "flight-safety-monitor" / "live-tuning-architecture-simulation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
