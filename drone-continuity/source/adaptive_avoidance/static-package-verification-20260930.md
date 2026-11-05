# Static firmware package verification

Date: 2026-09-30

Scope: read-only verification of `outputs/avoidance-correction-20260930` and the isolated source at `/home/daddy_nate/ardupilot-adaptive-clean`. No hardware, parameter, flash, or source operation was performed.

Result: **PASS**. No static packaging blocker was found.

## APJ and application image

- APJ magic: `APJFWv1`
- Board: `MicoAir743v2`
- Board ID: `1179`
- Firmware base identity: `dbe79216` / full source base `dbe792162d06cab66c3475fd5556bf7a120f119e`
- APJ `image_size`: `1,435,316` bytes
- Decoded APJ image length: `1,435,316` bytes
- `application.bin` length: `1,435,316` bytes
- Decoded APJ image equals `application.bin` byte-for-byte.
- Application SHA-256: `181b7c107fe9d84d3403d205afb3bd28064d415ad7cc7d8770723d2b9842f00e`, matching the manifest.
- APJ SHA-256: `c88db811b737c351e3bf8f60c4d9cdbcae00892c52fe3567f9e15a2ebc990c75`, matching the manifest.
- APJ maximum image size: `1,703,936` bytes; reported free space `268,620` bytes equals maximum minus image size.

## Address and erase bounds

- Board definition declares `FLASH_SIZE_KB 2048`, application `FLASH_RESERVE_START_KB 128`, and `STORAGE_FLASH_PAGE 14`.
- Application start: `0x08020000`.
- Computed application end, exclusive: `0x0817E6B4`, matching the manifest.
- With 128 KiB H743 sectors, the application occupies sectors 1 through 11.
- Required erase interval is `0x08020000` through `0x08180000` exclusive.
- Storage starts at `0x081C0000` (sector/page 14), leaving `0x40000` bytes between the rounded application erase end and storage.
- The rounded erase interval excludes the 128 KiB bootloader sector 0 and storage sector 14.

## Vector table

- Initial stack pointer: `0x30000600`, in STM32H743 SRAM.
- Reset vector: `0x08020DB9`; Thumb bit is set and the target address is inside the application image.
- All first 15 exception-handler vectors after the stack pointer have the Thumb bit set and target addresses inside the application image.

## Embedded parameter strings

The application image contains the group prefixes `AVOID_` and `RNGFND`, plus `MAV_PORT`, `ADAP_EN`, `ADAP_RT`, `ADAP_MAX`, `ADAP_HADD`, `ADAP_HON`, and `ADAP_HOFF`. ArduPilot stores the group prefix and member names separately, so a contiguous `AVOID_ADAP_EN` string is not expected.

The adaptive fields extend the existing `AC_Avoid` group safely:

- existing parameter indices 1, 3 through 11 are unchanged; index 2 remains reserved;
- new fields use unique appended indices 12 through 17;
- field types are stable (`AP_Int8` for enable and `AP_Float` for the five numeric settings);
- `AP_Param::setup_object_defaults(this, var_info)` initializes them through the existing object lifecycle;
- full names after applying the existing `AVOID_` group prefix are at most 15 characters, within ArduPilot's 16-character parameter-name limit;
- runtime-only adaptive state is not present in `var_info` and is therefore not serialized.

## Source and patch preservation

- `complete-source.patch` contains exactly the approved 13 source files.
- The current isolated source diff, `complete-source.patch`, and `adaptive_avoidance/arducopter-4.7.1-directional-adaptive-margin.patch` are byte-for-byte identical.
- Complete patch SHA-256: `a711637b05257fba23bbf1c0102fd371c2f9a0a334e183a7fb4bbe4823571a36`, matching the manifest.
- `git diff --check`: pass.
- The six routing files remain byte-for-byte identical to `outputs/rangefinder-port-filter.patch`.
- Routing patch SHA-256: `12f8ad1977be67a34ac994033b0ce2027821fea25611ad05a00bb6d2ceae0f53`.

Approved source-file list:

1. `ArduCopter/sensors.cpp`
2. `ArduCopter/system.cpp`
3. `libraries/AC_Avoidance/AC_Avoid.cpp`
4. `libraries/AC_Avoidance/AC_Avoid.h`
5. `libraries/AP_Proximity/AP_Proximity.h`
6. `libraries/AP_Proximity/AP_Proximity_Boundary_3D.cpp`
7. `libraries/AP_Proximity/AP_Proximity_Utils.cpp`
8. `libraries/AP_RangeFinder/AP_RangeFinder.cpp`
9. `libraries/AP_RangeFinder/AP_RangeFinder.h`
10. `libraries/AP_RangeFinder/AP_RangeFinder_MAVLink.cpp`
11. `libraries/AP_RangeFinder/AP_RangeFinder_Params.cpp`
12. `libraries/AP_RangeFinder/AP_RangeFinder_Params.h`
13. `libraries/GCS_MAVLink/GCS_Common.cpp`

## Backup and planned parameters

The fresh backup `outputs/pre-install-avoidance-20260930_0350` contains 1,329 unique parameters in both `.param` and `.json`; their key sets match exactly.

Pre-install values:

- `AVOID_MARGIN=1`
- `PRX_FILT=0.25`
- `LOIT_SPEED_MS=12.5`
- `AVOID_ADAP_EN` is absent, as expected for the old firmware.

The manifest plans exactly three changes:

- `AVOID_ADAP_EN=1`
- `PRX_FILT=5`
- `LOIT_SPEED_MS=2`

`AVOID_MARGIN` is not in the change set and remains 1 metre.

## Failed installation record

`installation.json` records stage `request_bootloader`, `flash_started=false`, `verified=false`, and error `Bootloader did not identify; no erase or programming attempted`. The log is consistent with a serial bootloader transition failure before erase or programming.
