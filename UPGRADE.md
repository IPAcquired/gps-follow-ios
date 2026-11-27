# Upgrade an enrolled R3.4 RC2 field console offline

Start with an Orange Pi that already runs the RC2 wired desktop. The Pi-only ZIP updates the sender and includes the companion desktop helpers. The complete ZIP also includes the optional E32R35T screen application, its matching partition table, build source and the previous application. Read **SCREEN.md** in the complete ZIP for the screen procedure.

### Stage and activate the Pi sender

Sign in as the graphical desktop owner, extract one archive into an empty local directory and open a terminal there. Save the rollback directory printed by the following commands. It holds the exact prior sender and local enrollment files and belongs in private storage.

```sh
sha256sum -c SHA256SUMS &&
umask 077 &&
work_dir="$(python3 -B upgrade_existing.py)" &&
printf '%s\n' "$work_dir" &&
python3 -B "$work_dir/upgrade/activate.py" stage &&
python3 -B "$work_dir/upgrade/activate.py" activate
```

### Enable lossless capture and responsive window behavior

The capture helper recognizes the two reviewed companion module hashes. A different local version requires a source review. The standard browser continues to receive its JPEG format. The paired local sender can request PNG and reuse a verified image while the pointer moves.

```sh
python3 -B companion/apply_capture_update.py check "$HOME/bin" &&
python3 -B companion/apply_capture_update.py apply "$HOME/bin" &&
systemctl --user restart orangepi-companion.service &&
systemctl --user is-active orangepi-companion.service
```

For a headless XFCE desktop, install the window-fitting fix. The second command saves the current GTK animation preference and disables animations for this desktop user.

```sh
python3 -B companion/window_fit_update.py install
python3 -B companion/desktop_animations.py disable
```

### Check the result

Connect the enrolled screen and mouse receiver to their normal Pi host ports. Unlock the graphical desktop and allow the companion to receive fresh disarmed controller status. Open the Applications menu, select an item and move the mouse back across the window. The pointer should leave one arrow, and menu text should become usable as the rest of the view finishes.

```sh
systemctl --user is-active orange-pi-wired-desktop-discovery.service
"$HOME/.local/bin/orange-pi-wired-desktop" status
```

### Roll back

Use the saved staging directory to restore the previous sender. Restore each companion option that you installed. The companion restart reloads the restored capture modules.

```sh
python3 -B "$work_dir/rollback/activate.py" activate
python3 -B companion/desktop_animations.py restore
python3 -B companion/window_fit_update.py restore
python3 -B companion/apply_capture_update.py restore "$HOME/bin"
systemctl --user restart orangepi-companion.service
```

The RC2 package and the matched RC1 kit are available from the project. [RC2 sender release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc2) · [Matched RC1 kit](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc1)
