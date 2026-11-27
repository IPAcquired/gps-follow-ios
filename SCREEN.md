# Optional E32R35T screen application

This update is for the enrolled Hosyond E32R35T resistive touchscreen with an ESP32-WROOM-32E-N4, 4 MiB flash, ST7796 display and the R3.4 `min_spiffs` partition layout. Use the Pi update by itself if the existing screen meets your needs.

| Item | Verified value |
| --- | --- |
| PlatformIO environment | `flight_team`, Arduino, `espressif32@6.12.0`, `esp32dev` |
| Screen version string | `flight-team-display-1.3.34-wired-paired-r3.4` |
| RC3 runtime identifier | `staging_slice_version` equals `2` in `wired_status` |
| Partition table | Offset `0x8000`, 3,072 bytes, SHA-256 `0a8b5720e7b77ff11f1462458c3a509dee79224e5279898f26d6a2e3ae0517b7` |
| Application slot | `app0` at `0x10000`, capacity `0x1e0000` |
| RC3 application | 1,506,848 bytes, SHA-256 `a99ab69d641a9c0eae099b907c785aa0a12337c7e2683bb6bc7aaf2edc2e55a9` |
| Previous RC1/RC2 application | 1,506,464 bytes, SHA-256 `ec28c584327837e2669b20d8ad0a8d4ed51ba517586052ced27dd0b31c592ad8` |

### Source and build

The complete application source is in `screen/`. The dependency versions, display settings and partition selection are in `screen/platformio.ini`. With the pinned PlatformIO toolchain and dependencies available locally, run `pio run --project-dir screen --environment flight_team`. The ordinary build target compiles the app. The included binary is identified by its SHA-256 above. Toolchain and build metadata can affect independently rebuilt bytes.

The reference build starts from the public RC1 source. Changes to `screen/src/main.cpp` and `screen/include/WiredPictures.h` are shown in `firmware/rc1-to-rc3.patch`. The screen's version string stays the same across this application update. Read the runtime identifier to distinguish the applications. File and toolchain details are recorded in `firmware/provenance.json`. [Matched RC1 source and application](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc1)

### Prepare an application-only update

Use the enrolled screen on its verified serial data connection with the controller disarmed. Check the board label, flash capacity, current application and calibration first. On the maintenance computer or Pi, use esptool 4.9 and assign the verified screen's serial device to `PORT`. Stop the display sender if it owns that same device, and restart it when finished. Run the commands below from the extracted archive.

Read the partition table and the current application sectors into a private directory. The `0x170000` span covers the same 368 flash sectors for both versions.

```sh
umask 077
backup_dir="$(mktemp -d)"
printf '%s\n' "$backup_dir"
python3 -m esptool --chip esp32 --port "$PORT" flash_id
python3 -m esptool --chip esp32 --port "$PORT" read_flash 0x8000 0xc00 "$backup_dir/partitions.bin" &&
cmp "$backup_dir/partitions.bin" firmware/reference-partitions.bin &&
python3 -m esptool --chip esp32 --port "$PORT" read_flash 0x1f0000 4 "$backup_dir/other-slot-header.bin" &&
python3 -c 'from pathlib import Path; import sys; b=Path(sys.argv[1]).read_bytes(); sys.exit(0 if len(b)==4 and b[0]!=0xe9 else 1)' "$backup_dir/other-slot-header.bin" &&
python3 -m esptool --chip esp32 --port "$PORT" read_flash 0x10000 0x170000 "$backup_dir/original-app-sectors.bin" &&
cmp -n 1506464 "$backup_dir/original-app-sectors.bin" firmware/E32R35T-r3.4-rc1-app.bin
```

Save the backup directory for rollback. Proceed when the board identity, 4 MiB capacity, prior app and partition table match and the screen runs from `app0`. The `reference-partitions.bin` file is for comparison. The update writes the single application image.

```sh
sha256sum -c SHA256SUMS &&
python3 -m esptool --chip esp32 --port "$PORT" write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 firmware/E32R35T-r3.4-rc3-app.bin &&
python3 -m esptool --chip esp32 --port "$PORT" verify_flash 0x10000 firmware/E32R35T-r3.4-rc3-app.bin
```

Restart the sender, reconnect through the existing pairing and check that the screen still reports calibration and the RC3 runtime identifier. Open Applications, move the mouse and tap a menu. An ordinary application-only update retains the screen's settings and enrollment in their existing partitions.

### Restore

Use the application-sector backup from this same screen. Restore and verify only the `app0` span, then restart the sender and check pairing and touch again.

```sh
cmp -n 1506464 "$backup_dir/original-app-sectors.bin" firmware/E32R35T-r3.4-rc1-app.bin &&
test "$(wc -c < "$backup_dir/original-app-sectors.bin")" -eq 1507328 &&
python3 -m esptool --chip esp32 --port "$PORT" write_flash --flash_mode keep --flash_freq keep --flash_size keep 0x10000 "$backup_dir/original-app-sectors.bin" &&
python3 -m esptool --chip esp32 --port "$PORT" verify_flash 0x10000 "$backup_dir/original-app-sectors.bin"
```
