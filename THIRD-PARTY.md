# Upstream components

The screen's bounded deflate decoder uses public uzlib sources. The original authors and terms accompany the implementation. [Included license](screen/lib/WiredInflate/LICENSE) · [uzlib project](https://github.com/pfalcon/uzlib)

The CORVON743V2 reference is a pinned ArduPilot board definition. The companion checks the included file's hash when reporting the offline reference. [Exact source revision](https://github.com/ArduPilot/ardupilot/blob/1f36df1c90dfe41131f8fc565bbcf190be4b2a84/libraries/AP_HAL_ChibiOS/hwdef/CORVON743V2/hwdef.dat) · [GPLv3](pi/controller-profile/COPYING-ArduPilot.txt)

PlatformIO resolves the screen's Arduino-ESP32 platform and the pinned TFT_eSPI, ArduinoJson, NimBLE-Arduino and QRCode libraries specified in its build file. The XIAO uses the Arduino-Pico core for RP2350. [Screen build configuration](screen/platformio.ini) · [Arduino-Pico](https://github.com/earlephilhower/arduino-pico)
