# E32R35T native telemetry display

This screen-only package is for an enrolled E32R35T running the exact R3.4 RC6 application. The Orange Pi desktop sender can keep its existing compatible version. Keep the downloaded ZIP, its checksum and the private recovery directory created on the Pi.

## Install

1. On the independently powered Pi, use the enrolled desktop owner's account. Verify the downloaded checksum with `sha256sum -c E32R35T-native-telemetry-rc1.zip.sha256`. Extract the archive into a new directory. From that directory run `sha256sum -c SHA256SUMS`.
2. Connect the paired, touch-calibrated screen through its approved USB attachment. Confirm the native menu can open, the local setup is intact, and the controller is connected and freshly disarmed. The updater rechecks current safety and enrollment evidence before writing.
3. Use the existing approved Python environment with esptool 4.9.0. Run `python3 -B screen_update.py install` as the normal owner. Let the update finish and the discovery service resume. Open the overview, sensors and telemetry details, then check rotation, changing readings and the disconnected state.
4. Keep the update directory and the owner-private recovery state at `~/.local/state/paired-display-native-telemetry1/`. It contains the original app-sector readback from this screen and its verified hashes.

## Restore RC6

Reconnect the same screen in the same approved USB port, confirm a fresh disarmed controller and run `python3 -B screen_update.py restore` from the extracted directory under the same account and environment. Wait for the discovery service to return. The updater restores the owner-private original app sectors, verifies their full readback and checks the running paired application. A rejected preflight requires correcting the reported binding, fresh guard, application or USB condition before retrying.
