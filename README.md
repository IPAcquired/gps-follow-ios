# Pi health and sensors

On the paired touchscreen select **Pi → Wired Desktop**. The upper-left corner shows the warmer CPU cluster and the current operating state reported by the Pi performance service. The outlined numbers float over the desktop. Clicking or touching the numbers operates the application underneath. Only the small edge tab intercepts input. Open **Applications → System → Pi health and sensors**, or hold the edge tab briefly, for the full sensor menu.

- Tap **‹** to tuck the numbers against the left edge. Tap **›** to bring them back. The tab also accepts horizontal drags and a right-click opens the sensor menu.
- Choose a category at the top. **Next** and **Prev** page through the readings. **Pin** puts that reading in the corner. Pin **CPU temperature** to return to the original temperature-and-state view. **Back** returns to the desktop.
- A pin follows the selected sensor instance. A stale or missing value shows a dash. The private view preference remembers the pin and whether you tucked it away.
- **Orange Pi** shows CPU temperature, operating state, CPU busy percentage, available memory, system storage, uptime, load and CPU clocks. **Temperatures** lists exported thermal zones. **Cooling / power** lists kernel cooling levels and measured hardware-monitor channels. A cooling level is a driver setting. A fan tachometer, voltage or current reading needs a supported measuring channel.
- **Controller** shows the selected controller's fresh heartbeat, arm status, mode and system state. **Flight sensors** lists the monitor's per-instance readings, units and sample freshness, including IMU, barometer, attitude, GPS, radio and power fields when supplied. Sensor accuracy depends on the sensor, its calibration and operating conditions. A received GPS packet can report no position fix.
- **Pi peripherals** shows camera capture availability and the configured C1 and 8×8 lidar ports. A visible serial port identifies an interface. A validated sensor producer must supply a measurement for a distance reading. The local menu reads the Pi's published observations and kernel counters; it opens no serial port.

The corner samples every two seconds while visible and updates its text when it changes. Tucking it away stops sampling while the dashboard is closed. The dashboard opens only on request. The native ESP32 telemetry pages remain available from **Sense → Orange Pi / Details**; the corner indicator belongs to the shared Linux desktop.

## Offline installation

Sign in as the Pi desktop owner. From the extracted archive:

```sh
sha256sum -c SHA256SUMS &&
python3 -B install.py
```

The indicator starts on the next graphical login. To start it immediately in that desktop, run:

```sh
"$HOME/.local/bin/orangepi-field-health" --overlay &
```

To restore the prior installed files, log out of the Pi desktop and run `python3 -B install.py --rollback` as the same owner. The personal display preference is stored under `~/.config/orangepi-field-health/`. This package requires the existing Python 3 GTK 3 desktop.
