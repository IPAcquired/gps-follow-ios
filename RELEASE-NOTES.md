# Wired field console R3.4 release candidate 1

R3.4 improves the enrolled touchscreen's direct USB desktop connection. The Pi compares lossless tile layouts for menus, dialogs and small controls and chooses a smaller update when it saves confirmed records and estimated bytes. The existing full-picture commit still handles the first display and zoom. The Pi and screen authenticate the session, and Linux input continues through the existing owner desktop checks.

This is a public prerelease. Direct end-to-end acceptance still requires an enrolled touchscreen attached to the Pi, a completed desktop image, physical input and a reconnect on the intended wiring.

Both ends start at 115,200 baud. After mutual authentication, the updated Pi and screen can negotiate 2,000,000 or 921,600 baud and confirm the new rate. Up to eight encrypted graphics fragments share a single USB exchange. The screen processes them between normal UI iterations and confirms reception before the Pi commits a complete JPEG. On a failed rate trial the Pi temporarily skips that rate. The screen returns to the base rate after 1.6 seconds without an authenticated downlink. A R3.3 screen uses the existing single-record transport.

The Pi keeps the authenticated connection alive while it waits for the first guarded desktop capture. It can reidentify the same display after a lost high-rate connection. The screen limits how many serial bytes it reads per UI iteration, so a noisy cable cannot consume an entire loop indefinitely.

On a direct desktop session, local X11 drawing can wake capture between periodic checks. This lets changes made with a mouse or keyboard attached to the Pi reach the sender sooner. The existing polling fallback continues when the local XDamage extension is unavailable.

The Pi can approve additional exact USB hub sockets for the existing screen after proving its pairing. The list stays in the owner's local profile. The XIAO uses the same R3.3 firmware included in this archive.

## Tested display scenes

In a 480 × 296 desktop fixture, the R3.3 direct serial format required 375 records for a settings dialog, 257 for an application menu and 17 for a button redraw. The updated Pi planner used 196, 138 and 13. At 115,200 baud, minimum outbound wire time fell from 6.20 to 2.94 seconds for the dialog, 4.25 to 2.05 seconds for the menu, and 257 to 201 milliseconds for the button. These figures exclude acknowledgements, LCD drawing and the Pi desktop's response. The full-picture photo, first paint and zoom produced the same JPEG bytes on this fixture. The compiled R3.3 receiver accepted the new dialog records in a native fixture and reproduced all 142,080 RGB565 pixels.

In the R3.4 native serial fixture, a 14,077-byte JPEG used 48 USB request/response exchanges for its 381 data fragments. The R3.3 single-record path used 381 exchanges for the same fragments. The picture header and final verified commit are separate. The fixture exercised 115,200, 921,600 and 2,000,000 baud settings using simulated serial timing.

On a Linux Xvfb virtual X11 display, the median interval from drawing to a changed captured frame dropped from 234.37 ms to 11.94 ms across 15 changes. The slowest sample dropped from 393.15 ms to 83.68 ms. Each version performed three captures during the 1.23-second idle interval. This test measured the capture side on the host, before serial transmission and LCD drawing.

## Hardware verification

On a physical E32R35T, flash readback matched the R3.4 application SHA-256 recorded in the manifest. The flash regions outside the application matched their pre-update contents. The ESP32 booted R3.4, retained enrollment, the local profile and touch calibration, reported storage ready and completed a 1 KiB write/readback test. The idle serial link completed 40 of 40 request/response checks at the default rate. Physical touchscreen-to-Pi-to-LCD latency and end-to-end operation at the negotiated high rates remain pending.

See the [offline update and rollback instructions](UPGRADE.md), [first-time commissioning guide](COMMISSIONING.md), [screen controls](screen/CONTROLS.md) and [build instructions](README.md#build-and-test).
