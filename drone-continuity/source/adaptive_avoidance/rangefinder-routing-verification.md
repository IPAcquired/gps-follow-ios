# Rangefinder UART-routing verification

Date: 2026-09-30

Candidate: `/home/daddy_nate/ardupilot-adaptive-clean`

Base commit: `dbe792162d06cab66c3475fd5556bf7a120f119e` (Copter 4.7.1)

Result: **PASS** for the requested source-preservation and focused native checks. No hardware operation, firmware installation, Waf build, or ArduPilot source edit was performed.

## Exact patch preservation

- Scoped the candidate diff to the routing files and compared it byte-for-byte with `outputs/rangefinder-port-filter.patch`.
- `cmp`: pass (`0`).
- Saved patch SHA-256: `12f8ad1977be67a34ac994033b0ce2027821fea25611ad05a00bb6d2ceae0f53`.
- Candidate scoped diff SHA-256: `12f8ad1977be67a34ac994033b0ce2027821fea25611ad05a00bb6d2ceae0f53`.
- `git apply --check --reverse`: pass (`0`).
- Scoped `git diff --check`: pass (`0`).
- The saved patch and matching candidate diff each contain **six** files, not seven:
  - `libraries/AP_RangeFinder/AP_RangeFinder.cpp`
  - `libraries/AP_RangeFinder/AP_RangeFinder.h`
  - `libraries/AP_RangeFinder/AP_RangeFinder_MAVLink.cpp`
  - `libraries/AP_RangeFinder/AP_RangeFinder_Params.cpp`
  - `libraries/AP_RangeFinder/AP_RangeFinder_Params.h`
  - `libraries/GCS_MAVLink/GCS_Common.cpp`
- `GCS_Common.cpp` passes the receiving UART with `rangefinder->handle_msg(msg, get_uart())`.
- `RNGFNDx_MAV_PORT` uses parameter group index **54** and defaults to `-1`.

## Focused native test

Adapted `work/generate_port_test.py` only in `/tmp/rf-route-test.vYil1a` so it extracted the methods from the isolated candidate. Compiled the generated C++ with:

`g++ -std=c++17 -Wall -Wextra -Werror -pedantic`

Executable result: **pass**.

Output:

`131072 compiled handler cases, two-instance isolation, and port routing checks passed`

Coverage included:

- exhaustive signed `ADDR` / byte `id` combinations for orientations 2 and 25;
- all four existing sensors at `ADDR=0`, with incoming packet orientation 25, routed over ports 0 through 9: only the sensor assigned to the receiving port accepted each packet;
- a null receiving UART rejected by every sensor with `MAV_PORT >= 0`;
- nonzero `ADDR=7` rejected packet ID 0 and accepted packet ID 7 on its correct port;
- wrong ports rejected before the backend ID/orientation selector.

## Preserved controller backup mapping

`outputs/pre-adaptive-patch-backup-20260930/controller-before-adaptive.param` preserves:

| Instance | Role | MAVLink port | Orientation | Type | Address |
|---|---|---:|---:|---:|---:|
| RNGFND1 | right | UART5 | 2 | 10 | 0 |
| RNGFND2 | left | UART4 | 6 | 10 | 0 |
| RNGFND3 | down | UART1 | 25 | 10 | 0 |
| RNGFND4 | front | UART2 | 0 | 10 | 0 |

`SERIAL1_PROTOCOL`, `SERIAL2_PROTOCOL`, `SERIAL4_PROTOCOL`, and `SERIAL5_PROTOCOL` are all `2` (MAVLink2) in that backup.

No correctness blocker was found in the requested UART-routing scope. The only discrepancy is descriptive: the authoritative saved routing patch has six files rather than seven.
