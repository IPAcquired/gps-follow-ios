# Display monitor 1.0.0

This release fixes a graphical-session blackout that can occur when a USB-C adapter reports a connected display before its display modes are available.

- Keep HDMI active while waiting for a usable USB-C display mode and while attempting the switch.
- Query RandR after the modeset. Disable HDMI under the default policy only after DisplayPort reports an active mode.
- Retry a failed modeset and recover when a display advertises its modes late or loses its active mode.
- Preserve automatic resolution selection and the optional dual-display layout.

Nine offline regression scenarios cover missing and delayed display modes, modeset errors, a command that reports success without activating an output, a temporary failure, a lower-resolution display, dual-display operation, disconnects, and loss of an active mode. These checks exercise the X11 helper. End-to-end video requires a physical adapter and display.
