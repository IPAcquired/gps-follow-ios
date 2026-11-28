# Orange Pi display sender

Use this sender with the matched R3.4 RC6 display and companion. Save the original RC6 kit. The release provenance lists the exact base and replacement source hashes. Run the following commands in a terminal as the existing signed-in desktop owner.

## Prepare the sender

Place the ZIP and checksum sidecar in the same directory. Choose a fresh extraction directory.

```sh
sha256sum -c Orange-Pi-E32R35T-R3.4-rc7-sender-cc2fa0582906.zip.sha256 &&
mkdir -m700 sender-update &&
unzip -q Orange-Pi-E32R35T-R3.4-rc7-sender-cc2fa0582906.zip -d sender-update &&
cd sender-update &&
sha256sum -c SHA256SUMS &&
python3 -B onbox.py prepare
```

Preparation verifies all 32 RC6 source files and the locally enrolled release. The stock installer builds and tests a separate immutable candidate release. The output identifies the private stage and immutable fallback paths on this Pi. Save them with the owner's local rollback records.

## Activate and check

```sh
python3 -B onbox.py activate &&
python3 -B onbox.py status
```

The install checks the enrolled release, starts the existing user service, and verifies its local-only socket policy. Open Wired Desktop from the paired screen in the normal disarmed owner session. Check a complete frame, pointer movement, taps, local Back and the saved orientation.

## Restore RC6

From the extracted kit directory run

```sh
python3 -B onbox.py rollback &&
python3 -B onbox.py status
```

Rollback uses the original saved enrollment and verifies all 33 original files. Restore RC6 before trying a different selection of sender modules. If the extracted kit is unavailable, use the saved private stage directory and the stock activation entry point.

```sh
python3 -B "$stage_dir/rollback/activate.py" activate &&
systemctl --user is-active orange-pi-wired-desktop-discovery.service
```

Set `stage_dir` to the path previously printed by `prepare`. Reopen Wired Desktop and check the cursor, touch, Back and orientation.
