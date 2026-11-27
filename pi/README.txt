Paired Orange Pi touchscreen

When the registered touchscreen is attached and its normal controls permit
desktop use, the Orange Pi and display authenticate each other. The Pi can
use the XIAO USB-to-SPI bridge or the approved direct USB cable. The Pi
prefers the XIAO. The user service starts automatically at boot and needs
only local UNIX sockets. The desktop image and touch events use encrypted
records over the cable.

Every verified connection opens the existing local Linux desktop after
a fresh mutual challenge. The optional Pattern command displays a
separate diagnostic on request only. An OS-locked, unavailable or
unsafe session pauses sharing. The service preserves the independent Linux
lock and maintenance approval.

Back belongs to the touchscreen. Use the Pi page's Wired Desktop button
to open the view again. Tapping acts as a left click. Pressing, moving
and releasing acts as a drag. Input begins after the first complete
picture has been confirmed by the screen.

On the R3 touchscreen, the first desktop picture transfers into a buffer
and appears after the screen checks and decodes the complete JPEG. The Pi
sends small changes as exact rectangles. Tap Keyboard on the bottom bar
to enter text and navigation keys. Hide returns the lower part of the
screen to the desktop. The bottom bar itself stays local.

R3.2 supports 1×, 2× and 3×. Select Zoom, choose a magnification, and
use the four directions to move a quarter of the visible width or height.
After the screen confirms the new picture, a tap selects the corresponding
position on the original desktop. Tap a text field before opening Keyboard.
If the active field changes, select the field again and reopen Keyboard.

From your ordinary Pi terminal:

  ~/.local/bin/orange-pi-wired-desktop status
  ~/.local/bin/orange-pi-wired-desktop pattern
  ~/.local/bin/orange-pi-wired-desktop pause
  ~/.local/bin/orange-pi-wired-desktop owner

The status contains a view state and counters. The "os_inputs" counter
advances after the existing Linux desktop broker accepts an actual tap
or drag, text, or key event. "updated_frame_after_input" records a changed OS frame after
input. "updated_lcd_after_input" records a subsequent full picture
acknowledged by the screen. These counters contain no image data or tap
positions. The synthetic test's measured milliseconds start when the Pi
receives a touch release and end at the authenticated drawing acknowledgement.

With R3, "last_source_capture_monotonic" and "last_lcd_ack_monotonic"
describe the same completed desktop picture, in seconds on the Pi's
monotonic clock. "staged_picture_commit_seconds" includes transfer and
display acknowledgement. The ESP's separate "jpeg_commit_ms" measures
its local decode and LCD write. Back dismisses automatic reopening for
the current attachment. The finite paired and broker leases require a
fresh challenge on renewal.

The shell commands change modes through the owner-local service. That service
is the sole USB owner. Pause stops display sharing until Owner or Pattern is
requested. The paired session never grants access to a replacement screen
or Pi by attaching its cable. Enrollment material is held separately in the
verified owner's private configuration.
