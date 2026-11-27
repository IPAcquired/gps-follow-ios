# Upgrade the enrolled RC3 Orange Pi sender

Extract the archive to an empty local directory on an already enrolled R3.4 RC3 Orange Pi. Sign in as the graphical desktop owner and run the following commands in that directory. Save the private staging-directory path for rollback.

```sh
sha256sum -c SHA256SUMS &&
umask 077 &&
work_dir="$(python3 -B upgrade_existing.py)" &&
printf '%s\n' "$work_dir" &&
python3 -B "$work_dir/upgrade/activate.py" stage &&
python3 -B "$work_dir/upgrade/activate.py" activate
```

With the enrolled display connected, the owner's desktop unlocked and the controller reporting fresh disarmed status, check the sender.

```sh
systemctl --user is-active orange-pi-wired-desktop-discovery.service
"$HOME/.local/bin/orange-pi-wired-desktop" status
```

Open a desktop menu, change a pinned health readout and move the pointer across the window. The updated label should settle into place with one visible mouse arrow. In the local sender status, `pointer_updates` counts acknowledged moves on both stationary and changing desktop content.

Use the private staging directory printed above to restore the previous sender.

```sh
python3 -B "$work_dir/rollback/activate.py" activate
```

The existing companion and screen application continue to work with this sender update. The corresponding complete package and screen instructions are in the [RC3 release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc3).
