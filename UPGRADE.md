# Install the USB stability update offline

This package updates an enrolled Orange Pi running the R3.4 RC1 wired desktop. The ESP32 keeps its existing R3.4 application. For a new installation, start with the [matched R3.4 RC1 kit](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc1).

Sign in to the Pi as the ordinary desktop owner. Unzip the update in a directory owned by that user. From that directory, run these commands.

```sh
sha256sum -c SHA256SUMS &&
umask 077 &&
work_dir="$(python3 -B upgrade_existing.py)" &&
printf 'Save this private rollback directory: %s\n' "$work_dir" &&
python3 -B "$work_dir/upgrade/activate.py" stage &&
python3 -B "$work_dir/upgrade/activate.py" activate
```

Leave the enrolled screen connected to its approved data socket. With the graphical session unlocked and the controller reporting fresh disarmed telemetry, check the display.

```sh
systemctl --user is-active orange-pi-wired-desktop-discovery.service
~/.local/bin/orange-pi-wired-desktop status
```

Look for `authenticated desktop visible` and tap a desktop menu. A new serious controller alert can interrupt the desktop. The screen shows that alert and resumes when the alert hold ends and the remaining checks pass. Use **Pi → Wired Desktop** to reopen the view after a manual Back.

Connect a mouse or its wireless USB receiver to the Pi's USB host hub. Move the pointer across a stationary window. The optional ESP32 field screen draws a contrasting arrow at the corresponding point. For a regular monitor, connect mini-HDMI directly to the Pi or use a compatible USB-C video dock on the middle data port. The monitor and receiver work independently of the ESP32. The left USB-C port supplies power on the Zero 3W.

To restore the exact previous sender, use the private directory printed during installation.

```sh
python3 -B "$work_dir/rollback/activate.py" activate
```
