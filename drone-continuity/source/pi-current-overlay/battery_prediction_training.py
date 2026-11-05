"""Small onboard battery-voltage predictor: actual SGD, candidate-only forever.

Prediction target is the next measured voltage 1–10 seconds later, not a flight
command, reserve estimator or avoidance decision. No Torch/Internet needed.
Unknown batteries train independently per BIN/monitor. Known physical packs can
combine logs only through owner-recorded immutable battery-store assignments.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import random
import time

import battery_profile_store as durable

ALGORITHM = "observed-battery-voltage-mlp-v2"
MAX_JOB_ROWS = 20000
MAX_JOB_LOGS = 32
MAX_RECORD_BYTES = 4096


def _preparer():
    path = Path(__file__).with_name("prepare-flight-training-data.py")
    spec = importlib.util.spec_from_file_location("battery_training_preparation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_row(row, expected_sha=None):
    if (not isinstance(row, dict) or type(row.get("schema")) is not int
            or row["schema"] != 1 or row.get("kind") != "battery_next_voltage"):
        raise ValueError("Not a battery telemetry target")
    durable._sha(row.get("flight_log_sha256"))
    if expected_sha is not None and row["flight_log_sha256"] != expected_sha:
        raise ValueError("Prepared row conflicts with the source log identity")
    durable._instance(row.get("instance"))
    if type(row.get("instance")) is not int or type(row.get("sequence")) is not int or row["sequence"] < 0:
        raise ValueError("Invalid telemetry ordering")
    if row.get("synthetic") is not False or row.get("label_source") != "observed_telemetry_not_human_reviewed":
        raise ValueError("Only actual observation-supervised telemetry can train this predictor")
    if row.get("armed") is not None and type(row["armed"]) is not bool:
        raise ValueError("Armed state must stay true, false or unknown")
    current = row.get("current_a")
    if type(row.get("current_measured")) is not bool or row["current_measured"] != (current is not None):
        raise ValueError("Current missingness must be explicit; unknown is not zero amps")
    if current is not None and (type(current) not in (int, float) or not math.isfinite(current) or not 0 <= current <= 1000):
        raise ValueError("Measured current must be a finite supported value or null")
    for key, low, high in (("voltage_v", .001, 100), ("target_voltage_v", .001, 100),
                           ("delta_seconds", 1, 10),
                           ("elapsed_seconds", 0, 1e10), ("time_us", 0, 1e16), ("target_time_us", 0, 1e16)):
        value = row.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("Missing or invalid measured battery target field")
    if abs((row["target_time_us"] - row["time_us"]) / 1e6 - row["delta_seconds"]) > 1e-6:
        raise ValueError("Next-voltage target is not the declared measured interval")
    if row.get("may_command_actuators") is not False or row.get("may_write_ardupilot_parameters") is not False:
        raise ValueError("Battery targets cannot acquire flight authority")
    for key in ("software_sha256", "sensor_calibration_sha256"):
        if row.get(key) is not None:
            durable._sha(row[key])
    return row


def features(row):
    # A zero with mask0 is an absent-feature encoding, never an estimated0A reading.
    return [row["voltage_v"] / 100., row["current_a"] / 1000. if row["current_measured"] else 0.,
            min(row["elapsed_seconds"] / 3600., 10.), row["delta_seconds"] / 10.,
            float(row["current_measured"])]


def initialize(seed=743):
    generator = random.Random(seed)
    return {"schema": 1, "algorithm": ALGORITHM, "architecture": "5-8-1-tanh-residual-volts-masked-current",
            "w1": [[generator.uniform(-.1, .1) for _ in range(5)] for _ in range(8)],
            "b1": [0.] * 8, "w2": [generator.uniform(-.01, .01) for _ in range(8)], "b2": 0.,
            "authority": "advisory_battery_prediction_only", "automatic_activation": False,
            "may_command_actuators": False, "may_write_ardupilot_parameters": False}


def _model_valid(model):
    if (not isinstance(model, dict) or type(model.get("schema")) is not int
            or model["schema"] != 1 or model.get("algorithm") != ALGORITHM
            or model.get("architecture") != "5-8-1-tanh-residual-volts-masked-current"
            or model.get("authority") != "advisory_battery_prediction_only"
            or model.get("automatic_activation") is not False or model.get("may_command_actuators") is not False
            or model.get("may_write_ardupilot_parameters") is not False):
        raise ValueError("Invalid predictor model identity or authority")
    if (len(model.get("w1", [])) != 8 or any(len(row) != 5 for row in model["w1"])
            or len(model.get("b1", [])) != 8 or len(model.get("w2", [])) != 8):
        raise ValueError("Invalid predictor weight dimensions")
    values = [value for row in model["w1"] for value in row] + model["b1"] + model["w2"] + [model.get("b2")]
    if any(type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 100 for value in values):
        raise ValueError("Nonfinite or unbounded predictor weights")


def predict(model, row):
    _model_valid(model)
    validate_row(row)
    x = features(row)
    hidden = [math.tanh(sum(weight * value for weight, value in zip(weights, x)) + bias)
              for weights, bias in zip(model["w1"], model["b1"])]
    return row["voltage_v"] + sum(weight * value for weight, value in zip(model["w2"], hidden)) + model["b2"]


def forecast_voltage(model, voltage_v, current_a=None, elapsed_seconds=0., horizon_seconds=1.):
    """Diagnostic inference from current readings; no future target required."""
    _model_valid(model)
    for value, low, high in ((voltage_v, .001, 100), (elapsed_seconds, 0, 1e10), (horizon_seconds, 1, 10)):
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("Diagnostic forecast inputs exceed their observed measurement bounds")
    if current_a is not None and (type(current_a) not in (int, float) or not math.isfinite(current_a) or not 0 <= current_a <= 1000):
        raise ValueError("Current must be supported measured amps or explicitly null")
    x = features({"voltage_v": voltage_v, "current_a": current_a, "current_measured": current_a is not None,
                  "elapsed_seconds": elapsed_seconds, "delta_seconds": horizon_seconds})
    hidden = [math.tanh(sum(weight * value for weight, value in zip(weights, x)) + bias)
              for weights, bias in zip(model["w1"], model["b1"])]
    prediction = voltage_v + sum(weight * value for weight, value in zip(model["w2"], hidden)) + model["b2"]
    return {"predicted_voltage_v": prediction, "persistence_baseline_voltage_v": voltage_v,
            "horizon_seconds": horizon_seconds, "current_measured": current_a is not None,
            "within_supported_voltage_range": .001 <= prediction <= 100,
            "diagnostic_only": True, "eligible_for_promotion": False,
            "may_command_actuators": False, "may_write_ardupilot_parameters": False}


def fit(rows, epochs=30, guard=None, progress=None, seconds_budget=120):
    if not 1 <= len(rows) <= MAX_JOB_ROWS or type(epochs) is not int or not 1 <= epochs <= 100:
        raise ValueError("Per-job training bounds exceeded; retained history is not deleted")
    for row in rows:
        validate_row(row)
    model = initialize()
    before = durable._hash(model)
    generator = random.Random(743)
    deadline = time.monotonic() + seconds_budget
    ordering = list(range(len(rows)))
    for epoch in range(epochs):
        if guard:
            guard()
        generator.shuffle(ordering)
        for offset, index in enumerate(ordering):
            if offset % 256 == 0:
                if time.monotonic() > deadline:
                    raise ValueError("Training time budget reached; no model was activated")
                if guard:
                    guard()
            row = rows[index]
            x = features(row)
            hidden = [math.tanh(sum(weight * value for weight, value in zip(weights, x)) + bias)
                      for weights, bias in zip(model["w1"], model["b1"])]
            delta = sum(weight * value for weight, value in zip(model["w2"], hidden)) + model["b2"]
            error = row["voltage_v"] + delta - row["target_voltage_v"]
            derivative = max(-10., min(10., 2 * error))
            old_w2 = list(model["w2"])
            for unit in range(8):
                inner = derivative * old_w2[unit] * (1 - hidden[unit] ** 2)
                for feature in range(5):
                    model["w1"][unit][feature] -= .01 * inner * x[feature]
                model["b1"][unit] -= .01 * inner
                model["w2"][unit] -= .01 * derivative * hidden[unit]
            model["b2"] -= .01 * derivative
        _model_valid(model)
        if progress:
            progress({"epoch": epoch + 1, "epochs": epochs, "training_rows": len(rows)})
    return model, {"initial_weight_sha256": before, "trained_weight_sha256": durable._hash(model),
                   "weights_changed": before != durable._hash(model), "epochs": epochs}


def evaluate(model, rows):
    if not rows:
        raise ValueError("Validation observations are missing")
    errors = [abs(predict(model, row) - row["target_voltage_v"]) for row in rows]
    baseline = [abs(row["voltage_v"] - row["target_voltage_v"]) for row in rows]
    return {"rows": len(rows), "mae_voltage_v": sum(errors) / len(errors),
            "maximum_abs_voltage_error_v": max(errors), "persistence_baseline_mae_v": sum(baseline) / len(baseline)}


def partition_group(rows, source_orders):
    logs = {row["flight_log_sha256"] for row in rows}
    if len(logs) >= 3:
        known_order = all(type(source_orders.get(digest)) is int for digest in logs)
        ordered = sorted(logs, key=lambda digest: (source_orders[digest], digest)) if known_order else sorted(logs)
        heldout = set(ordered[-max(1, len(ordered) // 5):])
        return ([row for row in rows if row["flight_log_sha256"] not in heldout],
                [row for row in rows if row["flight_log_sha256"] in heldout],
                {"whole_log_holdout": True, "heldout_log_sha256": sorted(heldout),
                 "source_chronology_known": known_order,
                 "split_policy": ("latest source-catalogue whole logs held out; arming is not takeoff proof" if known_order
                                  else "deterministic SHA-order whole-log holdout; source chronology unknown")})
    if len(logs) != 1:
        raise ValueError("Two logs are insufficient for whole-log holdout; await a third or train separately")
    ordered = sorted(rows, key=lambda row: (row["time_us"], row["sequence"]))
    split = max(1, int(len(ordered) * .8))
    cutoff = ordered[split]["time_us"] if split < len(ordered) else math.inf
    training = [row for row in ordered[:split] if row["target_time_us"] < cutoff]
    return training, ordered[split:], {"whole_log_holdout": False, "heldout_log_sha256": [],
                "split_policy": "same-log chronological diagnostic only; purge overlapping target boundary"}


def _read_candidate(path, job_id, job):
    payload = durable._read(path)["payload"]
    report = payload.get("report")
    model = payload.get("model")
    if (payload.get("schema") != 1 or payload.get("kind") != "battery_prediction_candidate"
            or payload.get("id") != job_id or payload.get("authority") != "advisory_only"
            or payload.get("job") != job or durable._hash(payload.get("job")) != job_id
            or not isinstance(report, dict) or report.get("candidate_id") != job_id
            or report.get("automatic_activation") is not False or report.get("eligible_for_promotion") is not False
            or report.get("may_command_actuators") is not False or report.get("may_write_ardupilot_parameters") is not False
            or report.get("trained_weight_sha256") != durable._hash(model)):
        raise ValueError("Immutable battery candidate identity or authority changed; evidence preserved")
    _model_valid(model)
    durable._uuid(payload.get("revision_id"))
    return report


def train_prepared(prepared_root, candidate_root, battery_store_root=None, guard=None):
    preparer = _preparer()
    prepared_dir = durable._directory(prepared_root) / "prepared"
    if not prepared_dir.exists():
        return {"state": "waiting_actual_battery_telemetry", "trained_candidates": [], "automatic_activation": False}
    assignments = {}
    if battery_store_root is not None and Path(battery_store_root).is_symlink():
        raise ValueError("Physical-pack history cannot be a link")
    if battery_store_root is not None and Path(battery_store_root).exists():
        for item in durable.list_observations(battery_store_root, read_only=True):
            if item["pack_id"] is not None:
                assignments[(item["log_sha256"], item["instance"])] = (item["pack_id"], item["assignment_sha256"])
    groups, orders, source_artifacts = {}, {}, {}
    for directory in sorted(prepared_dir.iterdir()):
        if directory.name.startswith(".pending-"):
            continue
        if guard:
            guard()
        metadata = preparer.read_metadata(directory, guard)
        digest = metadata["flight_log_sha256"]
        orders[digest] = metadata.get("source_order")
        source_artifacts[digest] = {"samples_sha256": metadata["samples_sha256"],
                                    "metadata_sha256": preparer.sha_file(directory / "metadata.json")}
        instances = metadata.get("efficiency_and_control_observations", {}).get("batteries", {})
        for instance_text in instances:
            instance = durable._instance(instance_text)
            binding = assignments.get((digest, instance))
            key = ("pack:" + binding[0] if binding else "unassigned-log:" + digest, instance)
            groups.setdefault(key, []).append((directory, digest, binding))
    candidate_root = durable._directory(candidate_root)
    results = []
    with durable._locked(candidate_root) as candidate_root:
        outputs = durable._directory(candidate_root / "candidates")
        for (identity, instance), members in sorted(groups.items()):
            # Hold only one training job's rows in RAM, never every log's row corpus.
            members.sort(key=lambda member: (orders.get(member[1]) if type(orders.get(member[1])) is int else -1, member[1]))
            selected_members = members[-MAX_JOB_LOGS:]
            group = {"rows": [], "seen": 0, "bindings": {}, "reservoir": random.Random(743)}
            for directory, digest, binding in selected_members:
                if binding:
                    group["bindings"][digest] = binding[1]
                last_sequence = -1
                with (directory / "samples.jsonl").open("rb") as stream:
                    while line := stream.readline(MAX_RECORD_BYTES + 1):
                        if len(line) > MAX_RECORD_BYTES:
                            raise ValueError("Prepared telemetry record exceeded its bound")
                        row = validate_row(json.loads(line), digest)
                        if row["sequence"] <= last_sequence:
                            raise ValueError("Duplicate or reordered telemetry sequence")
                        last_sequence = row["sequence"]
                        if guard and last_sequence % 512 == 0:
                            guard()
                        if row["instance"] != instance:
                            continue
                        group["seen"] += 1
                        if len(group["rows"]) < MAX_JOB_ROWS:
                            group["rows"].append(row)
                        else:
                            index = group["reservoir"].randrange(group["seen"])
                            if index < MAX_JOB_ROWS:
                                group["rows"][index] = row
            rows = group["rows"]
            if not rows:
                results.append({"identity": identity, "instance": instance,
                                "state": "waiting_more_valid_measured_pairs", "eligible_for_promotion": False})
                continue
            # Explicit pack history with only two logs remains per-log diagnostic.
            logs = sorted({row["flight_log_sha256"] for row in rows})
            batches = [rows] if len(logs) != 2 else [[row for row in rows if row["flight_log_sha256"] == digest] for digest in logs]
            for batch in batches:
                train, validation, split = partition_group(batch, orders)
                if len(train) < 20 or len(validation) < 5:
                    results.append({"identity": identity, "instance": instance, "state": "waiting_more_valid_measured_pairs",
                                    "training_rows": len(train), "validation_rows": len(validation), "eligible_for_promotion": False})
                    continue
                corpus = sorted((row["flight_log_sha256"], row["sequence"]) for row in batch)
                job = {"algorithm": ALGORITHM, "identity": identity, "instance": instance,
                       "source_artifacts": {digest: source_artifacts[digest] for digest in sorted({row["flight_log_sha256"] for row in batch})},
                       "explicit_pack_assignments": group["bindings"], "corpus_rows_sha256": durable._hash(corpus),
                       "split": split, "epochs": 30}
                job_id = durable._hash(job)
                existing = outputs / (job_id + ".json")
                if existing.exists():
                    report = _read_candidate(existing, job_id, job)
                    results.append({**report, "training_performed_this_run": False})
                    continue
                if guard:
                    guard()
                model, trained = fit(train, guard=guard)
                evaluation = evaluate(model, validation)
                if guard:
                    guard()
                report = {"candidate_id": job_id, "identity": identity, "instance": instance,
                          "state": "diagnostic_candidate_ready", "training_rows": len(train),
                          "validation_rows": len(validation), "seen_measured_rows": group["seen"],
                          "job_rows_retained": len(batch), "retained_history_logs_for_identity": len(members),
                          "selected_job_logs": len(selected_members),
                          "sampling": "One job at a time, up to32 source-catalogue latest logs and20000 deterministically sampled rows; all raw and prepared history retained.",
                          **trained, **split, "validation": evaluation,
                          "improves_persistence_baseline": evaluation["mae_voltage_v"] < evaluation["persistence_baseline_mae_v"],
                          "sensor_calibration_known": all(row.get("sensor_calibration_sha256") is not None for row in batch),
                          "software_build_known": all(row.get("software_sha256") is not None for row in batch),
                          "armed_pairs": sum(row["armed"] is True for row in batch),
                          "current_measured_pairs": sum(row["current_measured"] for row in batch),
                          "current_unknown_pairs": sum(not row["current_measured"] for row in batch),
                          "airborne_flight_confirmed": False, "eligible_for_promotion": False,
                          "qualification": "Unqualified advisory candidate; next-voltage accuracy is not battery reserve, life, savings or flight-control safety. Needs calibrated sensors, confirmed pack/flight identity and owner review.",
                          "automatic_activation": False, "may_command_actuators": False,
                          "may_write_ardupilot_parameters": False}
                durable._commit(candidate_root, "candidates", job_id,
                                durable._payload("battery_prediction_candidate", job_id, job=job, model=model, report=report))
                results.append({**report, "training_performed_this_run": True})
    return {"schema": 1, "state": "candidate_training_completed" if results else "waiting_actual_battery_telemetry",
            "trained_candidates": results, "automatic_activation": False,
            "eligible_for_promotion": False, "may_command_actuators": False,
            "may_write_ardupilot_parameters": False}


def summarize_candidates(reports):
    """Separate retained trained models from outcomes still waiting for data.

    This is reporting only. Existing immutable candidates and their canonical
    hashes are never rewritten, and a reused candidate is not new weight work.
    """
    candidates = [report for report in reports
                  if report.get("state") == "diagnostic_candidate_ready"
                  and report.get("weights_changed") is True]
    trained_this_run = sum(report.get("training_performed_this_run") is True for report in candidates)
    return {
        "dataset_count": len(reports), "candidate_count": len(candidates),
        "trained_count": len(candidates), "trained_this_run": trained_this_run,
        "waiting_count": len(reports) - len(candidates),
        "summed_training_rows": sum(report.get("training_rows", 0) for report in candidates),
        "summed_validation_rows": sum(report.get("validation_rows", 0) for report in candidates),
        "row_aggregate_scope": "retained_diagnostic_candidates_only",
        "actual_weights_updated": trained_this_run > 0,
        "actual_voltage_rows": sum(report.get("seen_measured_rows", 0) for report in candidates),
        "current_measured_pairs": sum(report.get("current_measured_pairs", 0) for report in candidates),
        "current_unknown_pairs": sum(report.get("current_unknown_pairs", 0) for report in candidates),
        "baseline_improved_count": sum(report.get("improves_persistence_baseline") is True for report in candidates),
        "whole_log_holdout_count": sum(report.get("whole_log_holdout") is True for report in candidates),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--battery-store-root", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    result = train_prepared(args.prepared_root, args.candidate_root, args.battery_store_root)
    if args.summary_only:
        reports = result.pop("trained_candidates")
        result.update(summarize_candidates(reports))
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
