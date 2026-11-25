# ArduCopter 4.7.3 R2 for CORVON743V2

This community firmware adapts ArduCopter's rangefinder and flight-mode handling for the CORVON743V2 flight controller, ArduPilot board ID `1229`. The November 25, 2026 source revision carries the R2 changes forward to Copter 4.7.3 and retains that release's Loiter default and CORVON743V2 hardware definition.

## Changes

- MAVLink rangefinders can be associated with an input serial port, sensor ID and physical orientation. Filtering distinguishes stale data, a sudden increase in reported distance and a fresh return beyond the configured range.
- Loiter and Guided velocity control can brake horizontally when a required rangefinder drops out. The optional directional proximity margin adds clearance according to closing speed. It is disabled by default.
- A pilot-operated RC switch can temporarily defer a battery-triggered Land in AltHold. The pilot assumes responsibility for landing while this is active. Loss of the required conditions releases the deferral and allows a pending Land to resume.
- A rangefinder fault can sound a buzzer alert, with higher-priority warnings taking precedence. R2 also corrects a Crossfire telemetry-rate calculation and the encoding of multi-element crash records.

## Scope

The [Orange Pi UART layout and optional telemetry profile](UART-LAYOUT.md) identify the companion link, two sensor ports and the USB camera connection.

The board has its own pin assignments and firmware ID. Select the exact CORVON743V2 board when building. Sensor orientation, calibration and avoidance behavior depend on the aircraft and its installed sensors. This release contains no flight-test qualification.

## Source and license

The complete R2 changes are in `complete-source.patch`. The source manifest identifies the upstream revision and its recursive dependencies. Build instructions include the commands for a clean checkout. [Build from source](BUILD.md) · [Source manifest](SOURCE.md)

ArduPilot is distributed under the GNU General Public License, version 3. The R2 modifications are distributed under the same license. Original per-file copyright and license notices remain in the pinned sources. Dependencies retain their own notices and licenses. [License text](COPYING.txt)
