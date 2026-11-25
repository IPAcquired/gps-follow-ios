# Corresponding source

ArduCopter Copter-4.7.3 is pinned to [`d9c5097c3d8333435712ffed86bca8ce00c4bb46`](https://github.com/ArduPilot/ardupilot/tree/d9c5097c3d8333435712ffed86bca8ce00c4bb46). Apply `complete-source.patch` to this revision. The patch contains the full R2 modification to 35 upstream source files as of November 25, 2026. [Board definition](https://github.com/ArduPilot/ardupilot/tree/d9c5097c3d8333435712ffed86bca8ce00c4bb46/libraries/AP_HAL_ChibiOS/hwdef/CORVON743V2) · [Upstream build scripts](https://github.com/ArduPilot/ardupilot/tree/d9c5097c3d8333435712ffed86bca8ce00c4bb46/Tools) · [Instructions](BUILD.md)

## Pinned dependencies

Git records every dependency below in its parent repository as a submodule. A recursive checkout at the base revision retrieves these commits, including nested dependencies. Each link opens the exact source tree and its original notices.

| Submodule path | Source revision |
| --- | --- |
| `modules/ChibiOS` | [`d103983f4362e5506bcf7062ccacf345fc0c0859`](https://github.com/ArduPilot/ChibiOS/tree/d103983f4362e5506bcf7062ccacf345fc0c0859) |
| `modules/CrashDebug` | [`599965086437137ec0fe66e185611f43f335f889`](https://github.com/ardupilot/CrashDebug/tree/599965086437137ec0fe66e185611f43f335f889) |
| `modules/CrashDebug/CrashCatcher` | [`4cf6e11df3a081b0f573a7834ed8e1e4000af73e`](https://github.com/ardupilot/CrashCatcher/tree/4cf6e11df3a081b0f573a7834ed8e1e4000af73e) |
| `modules/CrashDebug/CrashCatcher/CppUTest` | [`011f371fdb5d7e441fb023be67295783e053df4a`](https://github.com/ardupilot/CppUTest/tree/011f371fdb5d7e441fb023be67295783e053df4a) |
| `modules/CrashDebug/mri` | [`b35c89451b41a45b7f5b580acaff555315ac88e2`](https://github.com/ardupilot/mri/tree/b35c89451b41a45b7f5b580acaff555315ac88e2) |
| `modules/CrashDebug/mri/CppUTest` | [`011f371fdb5d7e441fb023be67295783e053df4a`](https://github.com/ardupilot/CppUTest/tree/011f371fdb5d7e441fb023be67295783e053df4a) |
| `modules/DroneCAN/DSDL` | [`04e0e818b06c180eb1720fcdf16484d0f12895ee`](https://github.com/DroneCAN/DSDL/tree/04e0e818b06c180eb1720fcdf16484d0f12895ee) |
| `modules/DroneCAN/dronecan_dsdlc` | [`de47a8972b7d8c59e50c3acfab5754db29798caa`](https://github.com/DroneCAN/dronecan_dsdlc/tree/de47a8972b7d8c59e50c3acfab5754db29798caa) |
| `modules/DroneCAN/libcanard` | [`601ed35467e0ac38819df17cd7c918de19f62d58`](https://github.com/DroneCAN/libcanard/tree/601ed35467e0ac38819df17cd7c918de19f62d58) |
| `modules/DroneCAN/libcanard/drivers/avr/avr-can-lib` | [`9c6bc9118de66d6edaf1b8539e2b9717ba26d123`](https://github.com/rennerm/avr-can-lib/tree/9c6bc9118de66d6edaf1b8539e2b9717ba26d123) |
| `modules/DroneCAN/pydronecan` | [`08cda37aaf2958657399606653b99ceb5a6beae0`](https://github.com/DroneCAN/pydronecan/tree/08cda37aaf2958657399606653b99ceb5a6beae0) |
| `modules/Micro-CDR` | [`3d1b17703c7cf4f22def2910bc845bdb5152d7b5`](https://github.com/ardupilot/Micro-CDR/tree/3d1b17703c7cf4f22def2910bc845bdb5152d7b5) |
| `modules/Micro-XRCE-DDS-Client` | [`97175304425c5bee87c6fddd99de1ef8d0c394dc`](https://github.com/ardupilot/Micro-XRCE-DDS-Client/tree/97175304425c5bee87c6fddd99de1ef8d0c394dc) |
| `modules/gbenchmark` | [`d572f4777349d43653b21d6c2fc63020ab326db2`](https://github.com/google/benchmark/tree/d572f4777349d43653b21d6c2fc63020ab326db2) |
| `modules/gsoap` | [`e1f690585d4803402584962bfaa8240ecaf1db30`](https://github.com/ArduPilot/gsoap/tree/e1f690585d4803402584962bfaa8240ecaf1db30) |
| `modules/gtest` | [`c5fed93f941865a0e912e9baf46ded713506590a`](https://github.com/ArduPilot/googletest/tree/c5fed93f941865a0e912e9baf46ded713506590a) |
| `modules/littlefs` | [`34be692aafaaf4319a18e415b08aa4332697408b`](https://github.com/ArduPilot/littlefs/tree/34be692aafaaf4319a18e415b08aa4332697408b) |
| `modules/lwip` | [`a6bf350c679ed8ba042ad58bf81cc540d61bb605`](https://github.com/ArduPilot/lwip/tree/a6bf350c679ed8ba042ad58bf81cc540d61bb605) |
| `modules/mavlink` | [`288b907c384a892c8519bfe271682424b1e1a3a0`](https://github.com/ArduPilot/mavlink/tree/288b907c384a892c8519bfe271682424b1e1a3a0) |
| `modules/mavlink/pymavlink` | [`ec06837a50688b5974094876c3c9d1b8bf86629d`](https://github.com/ArduPilot/pymavlink/tree/ec06837a50688b5974094876c3c9d1b8bf86629d) |
| `modules/waf` | [`35eadbb64e2052099a853b571e507c33032b392c`](https://github.com/ArduPilot/waf/tree/35eadbb64e2052099a853b571e507c33032b392c) |
