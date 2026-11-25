# Bridge changes

## 1.0.0

The Windows sender now pairs a controller’s exact USB serial number with the Pi’s verified SSH host key. It checks receiver compatibility before claiming the COM port, then rechecks the attached USB device in case it changed during the handshake.

Three challenge–response samples map PC capture time to the Pi’s clock. The sender rejects excessive delay or contradictory samples, and starts a new session after a clock jump or when calibration expires.

The sender keeps each complete MAVLink heartbeat in its own forwarded record, verifies the heartbeat checksum and records the controller source it observed. The Pi reports the selected monitor input back over the same SSH session. Its confirmation expires when the heartbeat or monitor status gets too old.

A separate Pi check also verifies delivery using two fresh, advancing heartbeats on the configured FIFO. The portable edition reads its profile from the operator’s private configuration and installs its serial dependency in a standard Python virtual environment.
