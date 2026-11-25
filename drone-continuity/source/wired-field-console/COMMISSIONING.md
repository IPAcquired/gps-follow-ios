# Commission a new installation

The desktop sender runs as the owner of a graphical Linux session. It expects the companion's local desktop broker and its existing flight safety policy. For typing, the broker needs the matching focus guard, its accessibility helper, xdotool and the signed-in owner's X11 authority. Review the supplied broker changes against a staging copy of the companion and run the focus fixtures there. The Orange Pi needs a working USB host port with a data cable. Wired pairing uses the Zero 3W's SoC identity from its Linux image and the touchscreen's eFuse identity. The XIAO carries encrypted records between those endpoints. [Focus broker integration](pi/focus-broker/README.md)

## Pair the boards

1. Start the normal local desktop, unlock it and ensure the companion broker is running under the same account. Check the hardware model, active slot and platform build before installing a screen app image. The authorized USB installer keeps NVS outside the application write.
2. Connect the screen's USB-C data port to the Pi host. If using the XIAO, connect its USB-C data port to its intended Pi host port as well. `python3 -m serial.tools.list_ports -v` shows the attached adapters locally. The commissioner verifies the CH340 bridge and the programmed XIAO USB identity, then obtains the screen's own firmware identity. Keep serial numbers and physical port paths local.
3. As the signed-in desktop owner, run the included `configure_pi.py` with the two paths as described in the README. Direct-only installations use `--screen-port` alone. The helper creates private local key material, checks screen enrollment and installs a systemd user service. A rerun on the same installation can resume an interrupted pairing.
4. Open **Pi → Wired Desktop**. A registered attachment can open the viewer from an idle Home or Pi page. **Back** dismisses that attachment. On the Pi, run `~/.local/bin/orange-pi-wired-desktop status` to check the selected route, session state, picture receipts and input receipts.

## Keep the other screen services

The normal controls and the wired session use separate authorization. For a blank touchscreen, calibrate the panel using the local setup prompt. Provision the local certificate hostname and approved home network through `--configure-network-policy`. Set up the companion's trusted CA certificate, authenticated time and the owner's network login with its existing physically local provisioning workflow. A wired-only desktop can operate with radios off while its Pi-side owner and safety checks pass. Ordinary Wi-Fi menus, Bluetooth phone sharing and SD recording use their own settings.

An existing owner can update only the verified screen application partition while retaining pairing and touch calibration in NVS. Keep the installer, full-chip backup and recovery material under the owner's control. A board replacement goes through the owner's recovery and fresh pairing workflow. The generic software has no copy of an installation's key, Wi-Fi password or trusted certificate.
