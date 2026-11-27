# Update an enrolled Pi offline

Use the existing desktop owner's Linux account and the complete release archive. The Pi-side update retains the installed USB topology, pairing, desktop policy and systemd user service. The same archive can be carried to the field on removable storage.

From the unpacked archive, verify its files, then prepare a private copy of the proposed release and a rollback copy of the exact active release.

```sh
sha256sum -c SHA256SUMS &&
umask 077 &&
work_dir="$(python3 -B upgrade_existing.py)" || exit 1
printf 'Upgrade and rollback directory: %s\n' "$work_dir"
python3 -B "$work_dir/upgrade/activate.py" stage
```

Save the directory printed above in your private operations notes. After the staging tests pass, activate the candidate and check the service.

```sh
python3 -B "$work_dir/upgrade/activate.py" activate &&
systemctl --user is-active orange-pi-wired-desktop-discovery.service &&
~/.local/bin/orange-pi-wired-desktop status
```

Keep the screen on the normal menu with the Pi's desktop signed in and unlocked. Connect the enrolled touchscreen to its approved Pi USB host socket with a data cable. Use the status command above to confirm that the selected route is **direct USB**, that the screen authenticated, and that a desktop image completed. Open a menu from the screen and confirm the change visually. A connected XIAO has priority if its own approved route is healthy.

The R3.4 Pi sender also supports the released R3.3 screen. Install the R3.4 touchscreen application to use the updated direct transport at both ends. See the [board and partition instructions](README.md#choose-a-board). The XIAO uses the existing R3.3 UF2.

When moving the already enrolled screen to a new USB hub socket, connect it, identify its current serial device with `python3 -m serial.tools.list_ports -v`, and run the following command as the desktop owner. Substitute the actual device for `/dev/ttyUSB0`.

```sh
python3 ~/.local/share/orange-pi-wired-desktop/current/screen_sockets.py --port /dev/ttyUSB0
```

Choose **Pi → Wired Desktop** on the touchscreen if prompted. The helper checks the existing pairing before saving that exact socket privately. The primary socket remains available. Reconnecting at an approved socket uses the same enrollment.

To return to the exact previous Pi release, use the saved directory.

```sh
python3 -B "$work_dir/rollback/activate.py" activate &&
systemctl --user is-active orange-pi-wired-desktop-discovery.service
```

The rollback changes the Pi-side service version. If the screen firmware was updated separately, use a compatible Pi sender or restore the owner's verified previous screen application using the documented board-specific recovery procedure. Keep configuration files, provisioned backups and the private staging directories on the owner's equipment.
