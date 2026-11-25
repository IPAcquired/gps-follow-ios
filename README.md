# Windows USB telemetry bridge for Orange Pi Zero 3W

Use this sender when a Windows PC has the ArduPilot flight controller connected over USB and an Orange Pi Zero 3W should receive its telemetry over SSH. The sender reads bytes from the selected controller. The companion’s existing monitor decodes the stream.

## What you need

- A USB controller advertising the ArduPilot device type supported by this sender, with a unique USB serial number. Close any other application that owns its COM port before starting.
- Windows with Python 3.10 or newer and the OpenSSH Client commands `ssh` and `ssh-keygen` on PATH.
- A reachable Orange Pi Zero 3W running the compatible telemetry monitor. Its unprivileged service account must allow SSH public-key login, have a writable monitor runtime directory, and hold the matching `pc-h743-input.py` and `pc_bridge_frame.py` in its own `~/bin`. Both receiver files are in the repository hosting this release, under `drone-continuity/source/pi-supporting-source/h743-usb-candidate/` at commit `71c0c10d7129884e9b352c144e3e98ca3a8e1e32`.

On the Pi, check that `systemctl is-active orangepi-mavlink-monitor.service` reports `active`. In the monitor’s existing configuration, `/etc/orangepi-mavlink-monitor.json`, the enabled serial transport for the bridge is `/run/orangepi-mavlink/pc-h743.fifo` at 115200. The monitor must support this framed FIFO. Preserve the other configured transports and their priority. The receiver creates its private FIFO when the session starts.

## Set up the sender

1. Extract this archive to a local working directory. From PowerShell in that directory, run the following commands.

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m serial.tools.list_ports -v
   ```

2. Identify the controller’s USB serial number from the last command. The fixed USB vendor/product pair used by the sender is `1209:5741`. The exact serial number goes in your private profile.

3. Check the Pi’s Ed25519 fingerprint at its own console or through an independently trusted administration session. The Pi command is `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`. In Windows OpenSSH, complete normal key-based login to that same device and compare the presented fingerprint before accepting its host key. The profile needs both that fingerprint and the matching host-name entry in your local `known_hosts` file.

4. Create your private profile and edit the copy. Insert the controller serial, the receiver account, the known-hosts alias, the verified fingerprint, your existing SSH key filename, and known Pi candidates. Use JSON path escaping or forward slashes.

   ```powershell
   $profileDir = Join-Path $env:USERPROFILE '.h743-pc-bridge'
   New-Item -ItemType Directory -Force $profileDir | Out-Null
   $profileFile = Join-Path $profileDir 'bridge.json'
   if (!(Test-Path -LiteralPath $profileFile)) {
       Copy-Item -LiteralPath .\bridge.example.json -Destination $profileFile
   }
   notepad $profileFile
   ```

   To store the profile elsewhere, set `H743_BRIDGE_PROFILE` to its filename before running the sender. For link-local IPv6, set `windows_link_local` to an object with `address` and `interface_name`. Enter the Pi’s verified link-local address without a zone suffix, and the interface name reported by Windows. The sender resolves its current scope index.

## Run and verify

Start the sender from PowerShell.

```powershell
.\.venv\Scripts\python.exe .\pc-h743-bridge.py
```

The sender checks the saved host key, receiver code hashes, active monitor service, configured FIFO and clock agreement before opening the matched COM port. A single sender owns the bridge on each Windows login session. It reconnects after a transport failure. Press Ctrl+C to stop it and release the port. Port and transfer status are recorded in `runtime/bridge-status.json` beside the private profile.

The status file lets you check both ends. An increasing `usb_heartbeats_expected` count means the PC received complete heartbeats with a valid checksum from ArduPilot system 1, component 1. The sender preserves the first-byte capture time across serial reads. On the same SSH session, the Pi reports its selected monitor input. A fresh `pi_fifo_verified` value of `true` means its monitor decoded at least two advancing heartbeats from its configured source on the bridge FIFO. A selected input of `native` means the monitor is using its onboard UART.

If the Pi corrects its clock during startup, the sender reports `recalibrating_pi_clock` and opens a fresh session with the paired Pi. Telemetry resumes after the monitor selects the PC input and receives fresh controller heartbeats. Start the updated sender with your existing private profile. The installed Pi receiver and controller firmware are compatible with this update.

Copy `check-pi-bridge-status.py` to the Pi through your existing trusted administration connection. With the sender running, execute `python3 -B check-pi-bridge-status.py` on the Pi. A successful result includes `fifo_verified: true`, two advancing fresh heartbeats and the FIFO as the selected transport. This distinguishes bytes sent by the PC from telemetry the Pi actually received. An already healthy preferred transport may keep the monitor on another input. The check reports which one it observed.

To run the offline tests on Windows, use `.\.venv\Scripts\python.exe -B -m unittest -v test_bridge`. The tests use synthetic data and a local subprocess. Completed tests establish software behavior. For an installed system, use the live heartbeat check above.
