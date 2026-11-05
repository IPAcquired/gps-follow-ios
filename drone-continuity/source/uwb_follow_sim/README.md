# Wearable UWB and Orange Pi desk verification

This is a bench-test candidate, not installed flight firmware. It contains no
MAVLink transmitter and does not arm, move, or flash the drone. A zero request
does not prove the aircraft will hover: the real integration must send the
correct stop command and have an independently tested flight-controller timeout.

## Hardware roles

- Wearable: one XIAO RP2350, one RYUW122_Lite, and a suitable protected 3.7 V
  single-cell battery connected to the XIAO's BAT pads. The battery powers the
  controller; its regulated 3.3 V output powers the UWB board. This is not an
  unpowered loose UWB board carried by the person.
- Drone: Orange Pi Zero **3W A733**, second RYUW122_Lite, RPLIDAR C1M1,
  MaixSense A010, USB camera/microphone and fan. No second RP2350 is required on
  the drone if the Orange Pi provides the verified UART and USB connections.
- Flight control remains with the H743, receiver and TX15 Max. Preserve their
  existing GPS, compass, radio and motor connections.
- UWB measures slant distance. A single pair provides neither 2D/3D position
  nor the bearing to a person. Camera/person association and aircraft navigation
  are still required for Follow. These tests do not contain a real vision model.

## Connections

| Connection | Required interface |
| --- | --- |
| XIAO D6 / GPIO0 | UWB RXD, 115200 baud, 3.3 V logic |
| XIAO D7 / GPIO1 | UWB TXD, 115200 baud, 3.3 V logic |
| XIAO 3V3 and GND | UWB VDD and GND; never battery voltage or 5 V on UWB VDD |
| XIAO D2 / GPIO28 | UWB NRST, with an appropriate external pull-down; test reset before enabling RF |
| Orange Pi UWB | A separately verified spare 3.3 V UART, TX to RX, RX to TX, common GND |
| RPLIDAR C1M1 | Separate UART at **460800**, 8N1, 3.3 V signals and its specified 5 V power; or its proper USB adapter |
| MaixSense A010 | USB recommended; keep its own frame parser and distance-unit conversion |
| Arducam | USB; check exact camera SKU, UVC/UAC formats, focus and orientation on the actual OS |
| H743 | Dedicated MAVLink connection; USB for the initial desk test |

The exact Orange Pi header pins have NOT been verified from the supplied board
and boot image. Do not copy Raspberry Pi, Orange Pi Zero 2W or Zero 3/H618 pin
maps. The Armbian A733 board definition reserves `/dev/ttyS1` for Bluetooth.
Use verified stable device identities, not the first `/dev/ttyUSB0` after reboot.
One device/service owns each UART. Windows COM9 is not H743 UART9.

## Power

Your existing **40 V buck converter** is now the proposed compute supply, but
its exact model, regulated output and continuous current remain unverified.
It must supply the correct **5 V** output with enough measured headroom for the
Orange Pi, camera, scanner, ToF board and fan. The model's 4 A load budget is an
assumption for testing, not a measured total or a converter rating.

Keep the existing 6 V servo supply separate from the compute 5 V supply and the
3.3 V UWB supply. Grounds must be common where non-isolated signal wires cross.
Do not parallel regulator positive outputs or backfeed supplies through USB.
Check available USB host sockets, port current limits and hub backfeed before
connecting everything. Do not load the flight controller's 5 V rail with the
entire companion system.

The landing gear needs two separate checks. Tower Pro lists 1.4 A stall current
per standard MG996R, so four simultaneous stalls would demand 5.6 A, above the
existing 5 A servo supply. The manufacturer's standard model is described as
0–159 degrees: a requested 270-degree path around the body cannot be assumed
available without a suitable linkage or different servo variant. The model
flags these optional gear/trick limits; it does not change any real servo output.

The alternative ZTW 6A UBEC lists a 25 V maximum input even though it also says
2–6S. A full 6S LiPo is 25.2 V. Confirm the exact revision's rating before using
that alternative; software cannot repair an input overvoltage condition.

## What changed

- Actual XIAO compilation fixed: preserve the SerialUART type for setTX/setRX;
  avoid the Arduino-generated prototype conflict with the noreturn attribute.
- Bound serial reads, transaction duration and message length. Require full
  acknowledgements, exact configuration readback, matching RF channel/bandwidth,
  and a nonzero privately provisioned AES key. Write flash only on a mismatch.
- An increasing eight-character tag payload exposes a frozen wearable MCU even
  if its radio keeps responding. It is a liveness counter, not a signature.
- Failures assert the wearable radio's reset line. Firmware watchdog and wrap
  handling were exercised with the actual sketch and mocked hardware.
- The request gate rejects invalid/future/stale values, sequence rollback,
  inconsistent ranges, uncertain target association, blocked/unknown obstacle
  coverage and missing flight authority. Recovery uses new samples.
- Pilot takeover stays cancelled until Follow is switched off and deliberately
  re-enabled. No reverse movement into an unseen rear area; face the target
  before moving forward. Slant distance is not treated as horizontal distance.
- A fresh valid empty scan can mean clear space. No response, corrupt data and
  an unobserved sector cannot be reclassified as clear space.

## Verification levels

1. Python tests and endpoint simulations verify the stated digital model.
2. Native C++ tests run the actual `.ino` against fake Arduino/UART/reset hardware
   with address/undefined-behavior sanitizers.
3. Arduino-Pico 6.2.0 compiles both the inhibited desk build and the operating
   code path for `rp2040:rp2040:seeed_xiao_rp2350` using public test credentials.
4. Electrical waveforms, RF multipath/body blockage, real camera recognition,
   outdoor ToF performance, actual NPU support, CPU latency and H743 braking
   are NOT proven by those tests. No hardware upload occurred.

The old stress run was only 20 seconds and missed several later faults. The
new 1,000 runs are each 60 seconds and record coverage of all 14 fault windows.

## Reproduce

From this folder with Python 3.10 or newer:

```text
python -m unittest -v
python run_scenarios.py
```

For native tests on Linux/WSL with g++:

```text
g++ -std=c++17 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -g -I native_test native_test/test_actual_sketch.cpp -o /tmp/uwb-sketch-tests
/tmp/uwb-sketch-tests
```

For the inhibited real-board compilation:

```text
arduino-cli compile --fqbn rp2040:rp2040:seeed_xiao_rp2350 --build-property compiler.cpp.extra_flags=-DUWB_DESK_TEST=1 xiao_tag
```

The resulting desk binary holds NRST low and does not enable the radio. The
operating path requires local UWB_AES_KEY provisioning and UWB_RESET_WIRED=1.
Do not flash the public-credential test fixture; it is not a release. Do not
publish private keys or a binary containing them. AES/key checks are not a
claim that the radio, apps or aircraft are unhackable.

## Sources

- [REYAX AT command guide](https://reyax.com/upload/products_download/download_file/AT_Command_RYUW122.pdf)
- [REYAX module electrical data](https://reyax.com/upload/products_download/download_file/RYUW122_EN.pdf)
- [Seeed XIAO RP2350 pin map and battery supply](https://wiki.seeedstudio.com/xiao_rp2350_arduino/)
- [Arduino-Pico source](https://github.com/earlephilhower/arduino-pico)
- [Armbian Orange Pi Zero 3W/A733 definition](https://github.com/armbian/build/blob/main/config/boards/orangepizero3w.conf)
- [SLAMTEC C1 specifications](https://www.slamtec.com/en/c1/spec)
- [MaixSense A010 packet, units and interface settings](https://wiki.sipeed.com/hardware/en/maixsense/maixsense-a010/at_command_en.html)
- [ZTW 6A UBEC voltage and current specification](https://www.ztwshop.com/product/accessory/2017/0814/ZTW-6A-UBEC.html)
- [Tower Pro MG996R voltage, current and standard travel](https://towerpro.com.tw/product/mg996r/)
