# Wired field console

The Hosyond E32R35T is a 480 × 320 resistive touchscreen with an ESP32-WROOM-32E. It displays the signed-in Orange Pi's graphical desktop and returns touch and keyboard input. A Seeed XIAO RP2350 can carry those records over USB and SPI. The alternative route goes straight from a Pi USB **host** connector to the display's USB-C serial interface. The Pi runs Linux and its apps on either route.

## Choose a board

| Target | Files | What runs there |
| --- | --- | --- |
| E32R35T resistive touchscreen | `screen/` | Normal controls, calibrated touch, desktop decoding, keyboard, SD logging and appearance. |
| Seeed XIAO RP2350 | `xiao/desktop_xiao/` | Native USB CDC, SPI with PIO and DMA, bus timeout handling, RGB and yellow lights. |
| Orange Pi Zero 3W | `pi/` | Owner-session service, desktop capture and input through the local broker, device pairing and USB route selection. |

The release ZIP includes `firmware/E32R35T-r3.3-app.bin` and `firmware/XIAO-RP2350-r3.3.uf2`. The touchscreen binary is the **application partition only** for the documented 4 MiB E32R35T layout, normally at `0x10000`. Verify the board, partition table and active application slot and retain an owner-private backup before updating an installed display. On an unprogrammed display, build the complete PlatformIO `flight_team` environment to obtain the matching bootloader and partition files. The UF2 image targets **Seeed XIAO RP2350**. Keep provisioned flash backups, keys and saved Wi-Fi profiles private.

## Connect the XIAO

With both boards powered down, use the ESP32 screen's **external SPI** connector. The ESP32 clocks this bus. Pin names below are taken from the board markings.

| E32R35T signal | XIAO RP2350 pin | Direction |
| --- | --- | --- |
| IO23 MOSI | D9 / GP4 | Screen to XIAO |
| IO19 MISO | D10 / GP3 | XIAO to screen |
| IO18 SCK | D8 / GP2 | Screen to XIAO |
| IO21 CS | D3 / GP5 | Screen to XIAO |
| GND on the adjacent connector | GND | Common reference |

Use 3.3 V logic. Power the XIAO from the Pi USB host and the screen from its normal USB supply. Leave the power pins between the XIAO and screen open. To test the direct USB route, power down, disconnect the SPI harness from the otherwise unpowered XIAO, and move the display's USB data cable to the Pi host connector chosen during enrollment. Leave the Pi's own power input in use.

## Enable a private desktop session

The supplied Pi adapter expects the companion project's local X11 owner broker, a signed-in and unlocked owner, a valid systemd user session and the approved fresh controller-state checks. Its socket lives under the desktop owner's runtime directory and must be owned by that user with mode `0600`. The adapter uses the Zero 3W's SoC identity for pairing. An alternative Pi image or computer needs a compatible local broker and board-identity implementation. Screen graphics and onboard lights can be built independently of this Pi installation.

1. Build or install the matching screen and XIAO releases. Calibrate the display. Install the Pi dependencies for Python 3, Pillow, pyserial and cryptography, plus the companion's local owner broker.
2. Unpack the release into a local directory. Verify the checksums against `SHA256SUMS`. On the Pi, connect the display by a data cable. For XIAO use, also connect the XIAO to its intended host port.
3. Run `python3 configure_pi.py --screen-port SCREEN_SERIAL --bridge-port XIAO_SERIAL` as the graphical owner. Replace both names with the locally verified device paths. For a direct-only installation omit `--bridge-port`. The installer records the identity of the selected XIAO locally so the same bridge can use another Pi USB host socket. For direct USB, use the host socket approved for the touchscreen. The optional `--configure-network-policy` prompts for the certificate hostname and approved Wi-Fi network used by the separate wireless setup. The real screen and Pi must prove possession of the same owner-specific key on connection. Fresh installs generate keys locally. A replacement device requires a new owner pairing.
4. Open **Pi → Wired Desktop** or attach the paired XIAO. Tap to click and drag to move the pointer. **Zoom** offers 1×, 2×, 3× and four pan directions. To type, tap the destination on the Pi desktop, then choose **Keyboard**. The Pi checks the active focus before enabling the local keys. **Back** leaves the desktop locally. Locking the Linux session or a safety guard that revokes the session stops remote interaction. Review and apply maintenance changes through the owner's existing workflow.

From the Pi terminal, `~/.local/bin/orange-pi-wired-desktop status` shows the route, display state and timing counters. `pause` pauses sharing, `owner` returns the service to normal desktop operation, and `pattern` explicitly selects the diagnostic squares. The normal startup opens the real desktop. [New installation and recovery](COMMISSIONING.md)

## Display, lights and storage

The screen reserves 16 KiB for a compressed full image at startup. It validates the complete image and draws it locally. Small changes use tiles or simple rectangles. The local LCD burst has no guaranteed synchronization with the panel's scan. A display refresh and an input acknowledgement are separate measurements. Full-image timings depend on image complexity, wiring, link rate and Pi load. The link authenticates both ends again when its finite session expires.

In **Setup → Lights & Appearance**, select a theme and color, then open **Backgrounds** for static or animated options. Animated decoration pauses during touch, desktop rendering and sensitive setup pages. **XIAO Lights** controls the bridge's onboard addressable RGB and yellow user indicator when the bridge is present. Its red charge light is controlled by hardware. The screen's own rear light has a separate control.

The ESP32 uses separate chip selects for its microSD card and the XIAO. The logger writes accepted sensor publications in the background. Use **Storage → Safe unmount** before removing a card. Missing, expired or unqualified sensor data is identified separately from genuine zero measurements. The configured controller for this layout is CORVON743V2. Its UART4 connects to Pi UART0. The C1 is assigned to Pi UART2, the 8×8 sensor to Pi UART7 and the camera to USB. A fresh MAVLink heartbeat indicates communication. The hardware target requires separate confirmation. The optional companion archive update groups completed logs by their recorded board and release before generating recommendations. [Historical log source groups](pi/controller-profile/ARCHIVE-GROUPS.md)

## Build and test

From this directory, verify the downloaded ZIP contents with `sha256sum -c SHA256SUMS`. The source release manifest records both firmware hashes and the touchscreen application version. Build the screen with PlatformIO and the XIAO with Arduino CLI and the Arduino-Pico 6.4.0 board package.

```sh
pio run -d screen -e flight_team
arduino-cli compile --fqbn rp2040:rp2040:seeed_xiao_rp2350 xiao/desktop_xiao
```

The Linux host tests use Python 3, Pillow, cryptography, pyserial, a C and C++ compiler, the mbedTLS 2.x development headers and the libjpeg development headers. The PlatformIO build supplies ArduinoJson 6.21.5. The tests use synthetic images, simulated serial devices and temporary storage. The Pi can use `python3-dbus` for its session checks.

```sh
python3 tests/run_regressions.py
```

Use `--arduinojson /path/to/ArduinoJson/src` for a separate installation of ArduinoJson. To exercise the integration against a separate staged companion release, add `--staged-companion /path/to/stage` after applying the companion profile and copying its integration fixture there. The package also tests the profile independently. See [screen controls](screen/CONTROLS.md) and the [companion profile guide](pi/controller-profile/README.md).

## Sources

- [E32R35T touchscreen hardware manual](https://www.lcdwiki.com/res/E32R35T/3.5inch_ESP32-32E_E32R35T_User_Manual.pdf)
- [Seeed XIAO RP2350 pin and LED reference](https://wiki.seeedstudio.com/xiao_rp2350_arduino/)
- [ArduPilot CORVON743V2 board definition and interfaces](https://ardupilot.org/copter/docs/common-corvon743v2.html)
