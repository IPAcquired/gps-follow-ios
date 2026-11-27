# Orange Pi postflight log intake 1.0.0

This add-on for the CORVON743V2 companion reads stored DataFlash logs from the flight controller after landing. It uses the existing Orange Pi telemetry monitor, UART0 and the connected controller's UART4 at its configured baud. A functioning return wire, an accessible flight-controller SD volume and a fresh controller report of disarmed standby and on-ground status are prerequisites for onboard collection.

## Operation

The monitor checks for a backlog after startup. A witnessed transition from armed to disarmed schedules another check after twelve seconds. The controller must have been in disarmed standby for five seconds and its selected heartbeat must be less than two seconds old. The monitor can request the current EXTENDED_SYS_STATE message. Only the matching controller's explicit landed-on-ground value, less than four seconds old, enables file traffic. Receiving an armed heartbeat, an airborne state, a conflicting controller, stale evidence or a flight/maintenance marker interrupts the transfer. The receive-only PC bridge continues to carry telemetry.

Open the existing companion desktop as usual. To inspect progress, run the following from a Pi terminal.

```sh
python3 -c 'import json; s=json.load(open("/run/orangepi-mavlink/status.json")); print(s.get("telemetry_provenance"),s.get("authority")); print(s.get("postflight_reader"))'
ls -lt ~/flight-data/acquisition/reports ~/flight-data/reports
```

The reader lists only the controller log directory and opens numeric BIN filenames and the logger's LASTLOG.TXT marker read-only. If directory enumeration fails, it can inspect one directory page of the volume root and APM, and try the current eight-digit filename named by the marker. Status contains presence and error codes. Complete transfers are size-checked, hashed and written into private storage. Transfers under 512 MiB and exactly 512 MiB are supported, with a 1 GiB local storage reserve. An interrupted transfer retries from the beginning. Failed jobs back off for 30 seconds, five minutes, fifteen minutes, then thirty minutes. The next witnessed disarm resets the delay.

| Location on the Pi | Contents |
| --- | --- |
| `~/flight-data/acquisition/snapshots/` | Private DataFlash copies named by content digest |
| `~/flight-data/acquisition/latest-analysis.json` | Most recently decoded current snapshot, including message types, duration, controller identity group and available flight-efficiency observations |
| `~/flight-data/acquisition/reports/` | One private summary per decoded snapshot digest |
| `~/flight-data/inbox/` | Completed logs staged for the existing analyzer |
| `~/flight-data/archive/`, `reports/`, `profile/` | Existing analyzer's archived sources, numerical reports and board-specific corpus |

One controller log may span several arm/disarm cycles. Its newest file stays provisional until the controller names a successor. A stable snapshot can be analyzed at each disarm while the aggregate profile counts only completed logs. An offline read-only FC card can finalize its files. The analyzer verifies controller metadata and segregates unattested or other-board logs. Its existing battery/profile consumers and the separate completed telemetry JSONL learning queue keep their existing inputs. A count of archived files alone does not establish an active-board flight or an accepted change.

Use the following commands to pause the reader and resume it. The files belong to the Pi's desktop owner.

```sh
touch ~/flight-data/acquisition/paused
rm -- ~/flight-data/acquisition/paused
```

To import an explicitly selected FC card, mount it read-only and use the actual mount point and filesystem UUID shown by `lsblk -f`. The importer checks the mount, UUID, source type and stability before sending a copy to the existing analyzer.

```sh
python3 /usr/local/lib/orangepi-postflight-intake/import_card.py /mnt/fc-card/APM/LOGS --expected-fs-uuid YOUR-FC-CARD-UUID
```

## Installation and rollback

Install on the compatible existing companion while the aircraft is parked and disarmed. Unpack the ZIP into a private directory and run the following there. The installer verifies the known monitor and three existing analyzer program digests, saves the original monitor and installs the immutable program copies. The service remains an unprivileged account with a private home view and explicit access to only two owner data directories. `ProtectSystem=strict` and `NoNewPrivileges=yes` remain active on the supported baseline.

```sh
sha256sum -c SHA256SUMS
sudo python3 -B install.py check
sudo python3 -B install.py activate
sudo systemctl daemon-reload
sudo systemctl restart orangepi-mavlink-monitor.service
systemctl is-active orangepi-mavlink-monitor.service
```

To restore the original monitor and its original service sandbox settings, run the following from the same release directory. Private logs and the original checksum-verified monitor backup remain available after rollback.

```sh
sudo python3 -B install.py rollback
sudo systemctl daemon-reload
sudo systemctl restart orangepi-mavlink-monitor.service
```

## Status and field troubleshooting

Monitor status distinguishes accepted observations from the auxiliary file reader's TX capabilities. `observed_from_matching_controller` describes the telemetry provenance. `read_only_postflight_file_queries` describes an active acquisition job or queries within the previous two seconds. Legacy consumers that require `read_only_no_mavlink_transmit` hold their protected action until passive operation resumes. Updates for accepted normal telemetry are coalesced at 100 ms; idle status is coalesced at 500 ms, subject to Linux scheduling and actual incoming messages.

A physically connected controller may still report an unavailable storage volume. `file_service_declined_list_2_28` is the controller's MAVFTP negative acknowledgment carrying errno 28. ArduPilot's FAT backend maps “volume has no work area” to this number. Check the FC's own SD slot, seating and readable FAT volume after removing its power. The Orange Pi's separate boot card has a different role. Use Mission Planner's DataFlash log listing or the read-only card importer to corroborate storage availability. Retain existing card contents.

## Verification and references

The frozen monitor installer and rollback, append/dedup handling, corrupt or interrupted inputs, exact allowed operations, duplicate/wrong receipts, source/landed/armed guards, existing approval guard behavior and publication cadence were checked with isolated fixtures. A genuine ArduPilot simulator on a loopback-only private namespace returned the requested landed state, listed and read two synthetic DataFlash files and delivered the closed file to the inbox. The installed analyzer implementation decoded the provisional snapshot. The test checked every simulated controller file after closing the session.

Protocol and storage details are documented by [MAVLink](https://mavlink.io/en/services/ftp.html) and [ArduPilot](https://ardupilot.org/copter/docs/common-downloading-and-analyzing-data-logs-in-mission-planner.html).
