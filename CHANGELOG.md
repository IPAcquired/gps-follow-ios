# Bridge changes

## 1.0.1

The sender reconnects to the paired Pi as soon as it detects that the Pi has corrected its clock. This fixes a startup delay of up to five minutes when network time synchronization happened just after the SSH handshake. The new session recalibrates timestamps before forwarding new controller packets. Repeated clock changes use the existing retry delay.

The monitor still requires two fresh, advancing controller heartbeats to confirm the PC input. The update runs on the Windows sender and works with the existing Pi receiver.

On Windows, a program reading the status file can briefly prevent replacement of that file. The sender now continues forwarding telemetry and publishes a fresh status on a later poll.

## 1.0.0

The Windows sender now pairs a controller’s exact USB serial number with the Pi’s verified SSH host key. It checks receiver compatibility before claiming the COM port, then rechecks the attached USB device in case it changed during the handshake.

Three challenge–response samples map PC capture time to the Pi’s clock. The sender rejects excessive delay or contradictory samples, and starts a new session after a clock jump or when calibration expires.

The sender keeps each complete MAVLink heartbeat in its own forwarded record, verifies the heartbeat checksum and records the controller source it observed. The Pi reports the selected monitor input back over the same SSH session. Its confirmation expires when the heartbeat or monitor status gets too old.

A separate Pi check also verifies delivery using two fresh, advancing heartbeats on the configured FIFO. The portable edition reads its profile from the operator’s private configuration and installs its serial dependency in a standard Python virtual environment.
