# Orange Pi telemetry, sensors and camera

This is the intended layout for a CORVON743V2 and Orange Pi Zero 3W. The port assignments are confirmed for the design. Physical signal, sensor-frame and camera-frame tests on this controller and companion are still pending.

| Endpoint | Connection | Purpose |
| --- | --- | --- |
| CORVON743V2 TELEM2, UART4 (`SERIAL4`) | Controller TX (PA0) to the Orange Pi UART0 RX and common signal ground | Receive flight-controller telemetry on the Pi at 115200 baud. This profile only requires the controller-to-Pi data line. |
| C1 lidar | Orange Pi UART2 | Sensor data goes to the Pi. Check the model's connection and baud rate before expecting a scan. |
| 8×8 time-of-flight matrix | Orange Pi UART7 | Sensor data goes to the Pi. Verify frames and orientation for the installed sensor. |
| USB camera | Orange Pi USB host port | Capture video through the camera's USB/UVC interface. |

Confirm the Pi exposes UART0, UART2 and UART7 on the chosen connectors. Check that the Pi's boot console or a login service is not using the telemetry UART. Identify each sensor by its output and the camera by a decoded video frame. The profile configures only telemetry transmission on the flight controller.

## Identify the MAVLink stream group

ArduPilot 4.7.3 numbers `MAV1_`, `MAV2_` and subsequent groups in the order that it finds MAVLink ports. The first port is group 1. Read `SERIAL0_PROTOCOL` through `SERIAL4_PROTOCOL` after boot. Count values **1, 2 or 43** (MAVLink 1, MAVLink 2 or high-latency MAVLink). Include SERIAL4 in the count and require `SERIAL4_PROTOCOL=2` for this profile. Registered virtual serial ports are considered after the built-in ports. [Serial manager](https://github.com/ArduPilot/ardupilot/blob/d9c5097c3d8333435712ffed86bca8ce00c4bb46/libraries/AP_SerialManager/AP_SerialManager.cpp#L600-L625) · [Stream group numbering](https://github.com/ArduPilot/ardupilot/blob/d9c5097c3d8333435712ffed86bca8ce00c4bb46/libraries/GCS_MAVLink/GCS.cpp#L77-L101)

| Port | Intended role | Protocol value | MAVLink group |
| --- | --- | ---: | --- |
| SERIAL0 | USB | 2 | MAV1 |
| SERIAL1 | TELEM1 | 2 | MAV2 |
| SERIAL2 | MSP DisplayPort | 42 | — |
| SERIAL3 | GPS | 5 | — |
| SERIAL4 | TELEM2 companion | 2 | **MAV3** |

For example, if SERIAL1 is disabled and the other four values match the table, SERIAL4 becomes **MAV2**. On that configuration, select the six `MAV2_` rates individually instead of importing the MAV3 profile. Changing a lower-numbered port's protocol can change the mapping on the next boot. [CORVON743V2 UART definitions](https://github.com/ArduPilot/ardupilot/blob/d9c5097c3d8333435712ffed86bca8ce00c4bb46/libraries/AP_HAL_ChibiOS/hwdef/CORVON743V2/hwdef.dat#L28-L77)

## Optional telemetry profile

Use [the seven-setting profile](corvon-uart4-pi-telemetry.param) only with the five protocol values shown above, standard non-inverted UART operation (`SERIAL4_OPTIONS=0`), and a dedicated TELEM2 connection. Check that no active serial passthrough uses UART4. With those prerequisites met, `SERIAL4_BAUD=115` selects 115200 baud. The remaining six settings are stream rates in hertz.

| Stream group | Parameter | Hz |
| --- | --- | ---: |
| Extended status | `MAV3_EXT_STAT` | 2 |
| Position | `MAV3_POSITION` | 5 |
| Attitude and related messages | `MAV3_EXTRA1` | 10 |
| Additional system and sensor messages | `MAV3_EXTRA3` | 2 |
| RC channels | `MAV3_RC_CHAN` | 5 |
| Raw sensors | `MAV3_RAW_SENS` | 5 |

After a disarmed reboot, read back the protocol map, baud setting and six rates. For a physical check, compare two reads of `@SYS/uarts.txt` and inspect the SERIAL4 transmit counters. Then verify that the Orange Pi receives a fresh MAVLink heartbeat and the expected message groups on UART0 while listening passively. Transmit counters alone cannot confirm reception. Individual message intervals can vary with bandwidth and stream requests. [ArduPilot UART diagnostic implementation](https://github.com/ArduPilot/ardupilot/blob/d9c5097c3d8333435712ffed86bca8ce00c4bb46/libraries/AP_HAL_ChibiOS/Util.cpp#L652-L674)
