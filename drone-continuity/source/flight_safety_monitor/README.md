# Flight Safety Monitor

This laptop-side tool reads ArduPilot DataFlash logs, records selected live
health telemetry, detects control oscillation and safety blockers, and prepares
bounded roll/pitch PID reductions for review.

One BIN may contain several armed flights. Each interval is analyzed
independently for control response, gyro peaks, vibration, clipping, motor
limits, crash and battery events, horizontal proximity coverage, downward
height, and ESC telemetry. Arm-up and touchdown transients are excluded from
the vibration and motor-limit screening window while explicit crash and
failsafe events remain visible.

The analysis is deterministic. An optional local Ollama model may explain the
finished report, but its text cannot enter the parameter-write path.

## Safety model

- Live monitoring is read-only.
- No parameter is changed automatically.
- Applying a proposal requires a matching confirmation token and a fresh
  disarmed heartbeat.
- Only roll and pitch rate P, I, and D are writable.
- Changes are reduction-only and limited to 10 percent per completed flight.
- A complete parameter backup is saved before the first write.
- Every write requires an acknowledgement and direct read-back.
- USB, serial, frame, motor layout, filters, sensors, avoidance, failsafes, and
  navigation parameters are protected and compared after the write.
- Any failed verification triggers rollback while the controller remains
  disarmed.
- A full-controller baseline records every parameter. Configuration drift,
  added parameters, or missing parameters blocks PID application.
- Calibration and runtime-counter drift are displayed separately for review.

## Analyze a flight log

```powershell
python flight_safety_monitor\flight_guard.py analyze --log outputs\dataflash-80.bin
```

The tool creates a machine-readable analysis, a proposal, and a readable
summary under `outputs\flight-safety-monitor`.

## Compare several logs

```powershell
python flight_safety_monitor\flight_guard.py batch `
  outputs\dataflash-80.bin outputs\dataflash-81.bin
```

The batch report compares every PID and filter parameter recorded in the logs.
It will not combine a tuning recommendation unless the selected flights use a
consistent baseline and pass every safety gate.

## Optional local-model explanation

The desktop app defaults to the balanced local model `qwen2.5:3b`. It checks
Ollama on startup and clearly reports whether that model is ready. The
model only receives the completed, bounded report and proposal summary. If
Ollama or the selected model is unavailable, the analysis still completes with
a deterministic explanation.

The local synthetic advisory benchmark completed in about 33 seconds with
`qwen2.5:3b`. `gemma4:26b` did not return an answer before a six-minute timeout,
so it is available as a manual option but is not the practical default.
Analysis runs on a worker thread so the UI remains responsive, and a timeout or
consistency failure returns the deterministic fallback.

For command-line analysis with Ollama:

```powershell
python flight_safety_monitor\flight_guard.py analyze `
  --log outputs\dataflash-80.bin `
  --llm-model qwen2.5:3b
```

The local model sees only the completed health report and proposal. Its output
is appended as an explanation and is never interpreted as settings.

## Read-only live monitor

Close Mission Planner before opening the serial port:

```powershell
python flight_safety_monitor\flight_guard.py monitor --port COM8 --seconds 60
```

## Applying a reviewed proposal

Read the generated summary and proposal first. Application is intentionally a
separate command:

```powershell
python flight_safety_monitor\flight_guard.py apply `
  --proposal outputs\flight-safety-monitor\proposal-TIMESTAMP.json `
  --confirm TOKEN_SHOWN_IN_ANALYSIS `
  --port COM8
```

Keep propellers removed during bench configuration. The short hover used to
validate a change must be conducted separately in a clear flight area.
