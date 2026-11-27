# Wired field console R3.4 RC2

This Pi-side update fixes the recurring loading and Critical screen on a wired ESP32 display. It also shows the Pi mouse pointer on the optional field screen. A monitor connected directly to the Pi uses the native desktop pointer and works with the touchscreen unplugged.

- The sender keeps the USB serial port open between sessions on the same physical attachment and changes the ESP32 reset control lines together. A fresh session still verifies the enrolled screen and desktop access.
- A screen connected through a USB hub starts its high-speed session at 921600 baud. A direct root-port connection can negotiate 2 Mbaud. New critical notices and the controller and desktop access checks remain active.
- The field screen tracks the local desktop mouse over stationary windows. Its high-contrast arrow follows the pointer hotspot, including when the wired view is zoomed. A USB mouse or wireless USB receiver connects to a host port on the Pi or its hub.

Apply this update as the desktop owner on an enrolled R3.4 RC1 Pi. The archive includes the installer, checksums, regression tests and rollback instructions. Keep the R3.4 touchscreen firmware installed. [Installation instructions](https://github.com/IPAcquired/gps-follow-ios/blob/wired-field-console-r3.4-rc2/UPGRADE.md) · [Matched R3.4 RC1 kit](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc1)
