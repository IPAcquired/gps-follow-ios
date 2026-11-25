# CORVON743V2 companion maintenance

Use `monitor` on the Orange Pi to inspect the running telemetry receiver. For an on-demand maintenance session, the Pi's UART0 TX and RX connect to the controller's TELEM2 UART4 RX and TX respectively, with a common ground. A direct flight-controller USB connection is also supported. Each requested operation runs once.

From the kit directory, run `/opt/drone/venv/bin/python companion_maintenance.py check` to verify the installed Python adapters and the pinned firmware package. This check uses local files only.

## Passive UART monitoring

```sh
python3 companion_maintenance.py monitor
```

The command reads the existing Orange Pi monitor's JSON publication at `/run/orangepi-mavlink/status.json`. It reports heartbeat age, publication age and arm state when both records are fresh, the source matches the monitor's expected source, and the published authority is receive-only. An unknown arm state is reported as `null`. This command uses the Python standard library. `--status-file` can select a previously captured status document for offline inspection.

## Review an adjustment

Use a root-owned installation of the kit for the system manager. Run these examples from a private directory writable by the monitor account. Set `kit=/usr/local/lib/corvon-maintenance` and `tool="$kit/companion_maintenance.py"`, adjusting the directory to the installed location. The examples use the established administrative account and system Python for systemd operations. The worker itself runs as the monitor account under its existing `/opt/drone/venv/bin/python` environment with pymavlink and pyserial. A system-managed handoff briefly releases UART0 for the foreground task and starts the monitor again when the worker exits.

```sh
sudo /usr/bin/python3 "$tool" plan --route pi-uart0 --proposal proposal.json
python3 "$tool" review --proposal proposal.json
```

`plan` reads identity and parameters and saves a proposal. `review` opens only that local file, prints the proposed changes and displays the SHA-256 digest. The owner can approve that exact digest after reviewing the changes. A proposal expires in 15 minutes. `audit --route pi-uart0` displays profile differences without creating a proposal.

To apply a reviewed proposal, supply its digest in a separate command. Replace `REVIEWED_SHA256` with the approved value. A fresh proposal is required if the controller, recorded pre-state, route, or proposal bytes change.

```sh
sudo /usr/bin/python3 "$tool" apply --route pi-uart0 --proposal proposal.json --approve REVIEWED_SHA256 --journal recovery.json
```

`apply` requires a fresh disarmed ArduCopter 4.7.3 heartbeat, board ID 1229, a device-bound approval and an on-ground report. It checks the protocol sequence `2,2,42,5,2` on SERIAL0 through SERIAL4, ordinary UART4 options and inactive UART4 passthrough. The following seven settings define the supported profile.

| Parameter | Value |
| --- | ---: |
| SERIAL4_BAUD | 115 (115200 baud) |
| MAV3_EXT_STAT | 2 Hz |
| MAV3_POSITION | 5 Hz |
| MAV3_EXTRA1 | 10 Hz |
| MAV3_EXTRA3 | 2 Hz |
| MAV3_RC_CHAN | 5 Hz |
| MAV3_RAW_SENS | 5 Hz |

Each changed setting is acknowledged and read back. The tool checks the full profile before reporting success. UART0 maintenance requires UART4 to be configured for 115200 baud. A correction to the active link's baud uses the independent USB route. In the examples, replace `--route pi-uart0` with `--route usb --port /dev/ttyACM0` and select the actual controller USB device. A baud correction can take effect on the next normal reboot. Run `audit` after that reboot to verify persistence, and use `monitor` to check Pi reception.

## Recover or undo an adjustment

Choose a new journal path for each change session. The journal contains the original settings and a device fingerprint. The approval includes restoring attempted settings if the update fails and the same controller is still grounded. If the connection is lost or the controller arms, recovery pauses. Keep the journal and review a separate recovery proposal after reconnecting the original, grounded controller. A setting that changed independently to a third value requires a new investigation.

```sh
sudo /usr/bin/python3 "$tool" plan-undo --route pi-uart0 --journal recovery.json --proposal undo.json
python3 "$tool" review --proposal undo.json
sudo /usr/bin/python3 "$tool" undo --route pi-uart0 --journal recovery.json --proposal undo.json --approve REVIEWED_UNDO_SHA256
```

## Prepare a firmware update

Firmware maintenance uses the same exclusive UART handoff and allows up to 40 minutes for the flash backup and transfer. The bundle directory must contain the pinned `CORVON743V2-4.7.3-R2.abin`. Choose an unused transaction directory beneath an existing private parent owned by the monitor's service account. The firmware check reads the installed image. When changes are needed, it stores backups and a proposal locally and prints its digest. If the application bytes already match, it reports `already-current`.

```sh
sudo /usr/bin/python3 "$tool" firmware-prepare --route pi-uart0 --bundle-dir "$kit" --transaction-dir ./private/fw-session
```

Review the proposed release, checksum, activation step and expiration before deciding whether to approve. The apply command requires the exact firmware proposal digest and rechecks the controller and its prior state before staging. Full readback precedes promotion to the bootloader's SD filename. Activation requires the owner's separate cold power cycle. Run verification after normal controller startup and reconnection. Cleanup requires an explicit command with the original approved digest and removes only the verified completed marker for this transaction. Pre-existing update files require separate investigation.

```sh
sudo /usr/bin/python3 "$tool" firmware-apply --route pi-uart0 --bundle-dir "$kit" --transaction-dir ./private/fw-session --approve REVIEWED_FIRMWARE_SHA256
sudo /usr/bin/python3 "$tool" firmware-verify --route pi-uart0 --bundle-dir "$kit" --transaction-dir ./private/fw-session
sudo /usr/bin/python3 "$tool" firmware-cleanup --route pi-uart0 --bundle-dir "$kit" --transaction-dir ./private/fw-session --approve REVIEWED_FIRMWARE_SHA256
```

The SD operation targets the included R2 application on this board. Raw flash, parameters, recovery journals and full proposals belong in private local storage. [Firmware format, verification and recovery](FIRMWARE.md)

The included firmware derives from ArduPilot and is distributed under GPL version 3. The release supplies the R2 source patch and the pinned upstream inputs for rebuilding it. [R2 source release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/corvon743v2-v4.7.3-r2) · [Firmware license](COPYING.txt)

## Offline tests

```sh
python3 -B -m unittest discover -v
```

The tests simulate telemetry freshness, identity and ground-state checks, profile mismatches, partial writes, interrupted recovery and undo. Live hardware qualification requires a separate bench check.
