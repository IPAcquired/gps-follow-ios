# Paired Orange Pi desktop in landscape and portrait

This offline update supports an enrolled E32R35T screen running the RC3 application, an Orange Pi running the RC4 sender, and the RC4 or RC5 companion capture modules. Keep the verified kit and the private staging directory printed during installation.

## Install on the Pi

1. Download the release ZIP and its checksum. Run `sha256sum -c Orange-Pi-E32R35T-R3.4-rc6-matched.zip.sha256` in the download directory. Extract the ZIP into an empty directory owned by your normal desktop account. Run the remaining commands from the extracted directory.
2. Verify the contents, then stage the new sender and its exact rollback. Save the path printed by the second command.

   ```sh
   sha256sum -c SHA256SUMS &&
   work_dir="$(python3 -B upgrade_existing.py)" &&
   printf '%s\n' "$work_dir" &&
   python3 -B "$work_dir/upgrade/activate.py" stage
   ```

3. Check the starting companion with `python3 -B landscape-base/display_update.py check`. If its two files show `original`, run `python3 -B landscape-base/display_update.py install` and record that step for rollback. If they show `installed`, proceed. Each installer checks exact file hashes and reports an unrecognized source.
4. Connect the enrolled screen through its approved USB port and keep the Pi powered separately. The owner session needs a live, freshly disarmed controller. Check that esptool 4.9.0 is available to the Python interpreter with `python3 -c 'import esptool; print(esptool.__version__)'`. Use your existing owner-approved loader environment. Then install the screen application.

   ```sh
   python3 -B screen_update.py install
   ```

   The updater stops display discovery temporarily, verifies the physical screen and partition layout, and saves a private, verified copy of the affected app sectors under `~/.local/state/paired-display-rc6/`. Keep this directory on the Pi for recovery. It verifies the written application, adjacent flash, original enrollment and touch calibration before returning.
5. Install the orientation-aware companion and activate the staged sender.

   ```sh
   python3 -B broker_update.py install &&
   python3 -B broker_update.py check &&
   python3 -B "$work_dir/upgrade/activate.py" activate &&
   systemctl --user is-active orange-pi-wired-desktop-discovery.service
   ```

## Use and verify both orientations

The sender gives cursor erasure and redraw priority when desktop content also changes. On an authenticated direct link it can combine a nearby move into one smaller transfer when it has already confirmed the exact background pixels. Full transfers, session changes and uncertain background pixels retain their ordinary redraw path.

Use **Back** to leave Wired Desktop. Select the desired screen orientation with the screen's existing rotation control, then open **Pi → Wired Desktop**. The desktop area is 480 × 296 pixels in landscape and 320 × 456 pixels in portrait. The bottom 24 rows hold the local controls, including **Back**. Set the viewer to its normal fit to see the complete desktop.

Check all four corners, the midpoint of each edge and the center. First tap targets on the glass. Then point to and click those targets using the wireless mouse. Check the health indicator and open the Pi sensor menu. Return with **Back** and check local screen menus and the phone connection.

## Restore the prior installation

The sender installer starts from R3.4 RC4 and records the exact active release, including the local USB enrollment, as its rollback. Keep the stage path printed during installation. An owner running a previous experimental RC6 sender should use that installation's saved rollback to return to the approved RC4 sender before preparing this matched kit.

Leave Wired Desktop. If the viewer reconnects automatically, pause capture with `systemctl --user stop orange-pi-wired-desktop-discovery.service`. Allow five seconds for the broker to restore the prior headless workspace. Confirm the current dimensions with `xrandr --current`.

1. Restore the sender using the exact saved staging directory. In a new terminal, return to the extracted kit and set `work_dir` to the full staging path recorded in install step 2.

   ```sh
   python3 -B "$work_dir/rollback/activate.py" activate
   ```

2. Restore the RC5 companion with `python3 -B broker_update.py restore`. If installation step 3 upgraded the original RC4 companion on this Pi, also run `python3 -B landscape-base/display_update.py restore`.
3. With the same enrolled screen connected and fresh disarmed status available, restore its original application sectors with `python3 -B screen_update.py restore`. After an interruption during a flash write, run this same command using the same kit. It checks the bound device and the existing private backup before proceeding.
4. Start display discovery with `systemctl --user start orange-pi-wired-desktop-discovery.service`. Reopen the display and check the baseline sender, screen input, and local menus.

## Rebuild the clean application

The public tag contains the screen source under `screen/`, its pinned PlatformIO environment, and the firmware digest under `firmware/provenance.json`. With the listed toolchain installed, run `pio run --project-dir screen --environment flight_team`. The build produces the application under `screen/.pio/build/flight_team/firmware.bin`. The release ZIP supplies the verified app-only images and the reference partition table. Compare the application SHA-256 and size with the provenance record when reproducing the published build. Toolchain and build metadata can affect independently compiled bytes.
