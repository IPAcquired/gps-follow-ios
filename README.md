# Orange Pi Zero 3W display monitor

This X11 session helper selects a display on the Allwinner A733 Orange Pi Zero 3W. It uses the RandR output names `DP-1` for USB-C DisplayPort and `HDMI-1` for the mini-HDMI socket. The kernel, display adapter, and session must already support those outputs.

## Try it

In the graphical user's terminal, run `xrandr --query` and check that the connector names match. The helper requires `/bin/sh`, `xrandr`, `awk`, and `logger`. Run one instance in the graphical session.

```sh
./orangepi-display-monitor
```

The default policy prefers USB-C display output. When RandR reports an available mode and confirms an active mode after the switch, the helper turns off the mini-HDMI output. It prefers 1080p at approximately 60 Hz when advertised and otherwise requests automatic mode selection. If DisplayPort has no usable mode, the helper selects a connected HDMI display. Press Ctrl+C to stop the helper.

To place HDMI to the right of an active USB-C display, set the dual-display policy at launch.

```sh
ORANGEPI_DISPLAY_POLICY=dual ./orangepi-display-monitor
```

For an existing installation, use `systemctl --user cat orangepi-display-monitor.service` to locate the executable and review the configured policy. Back up that executable, replace it with the release script while preserving its owner and executable mode, then run `systemctl --user restart orangepi-display-monitor.service` within the graphical user's session.

## Run the regression suite

Use stock Python 3 on Linux. The suite runs the supplied shell monitor against temporary stand-ins for RandR, logging, and polling. It does not need a display.

```sh
python3 -B test_display_monitor.py
```

For a hardware check, connect a working mini-HDMI display and connect the USB-C adapter with its display detached. HDMI should remain usable. Attach the second display and compare the mode marked with `*` in `xrandr --query` with the image seen on that display. Unplug the USB-C adapter and check that mini-HDMI returns.
