# Pi health and sensors 1.0.1

Adds a compact temperature and operating-state readout on the Orange Pi desktop and its paired field screen. Outlined numbers have a transparent background. Touches and mouse clicks pass through the numbers to the underlying application. Only the edge tab handles input. Tap it to tuck or restore the readout, or hold it to open the full sensor menu. The selected metric persists across login.

The touch menu exposes kernel thermal, cooling, CPU, memory and storage measurements alongside timestamped controller and peripheral observations. Missing data, expired fields and source mismatches suppress the previous value. The menu uses the existing local monitor and requires no network service or flight-controller access credentials.

Offline installation includes an application-menu entry, a graphical-login launcher and rollback. The wired desktop retains its existing authentication and disarmed-controller checks.
