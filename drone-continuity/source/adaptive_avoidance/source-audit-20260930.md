# Installed-source bounded audit

Date: 2026-09-30

Scope: read-only audit of `/home/daddy_nate/ardupilot-adaptive-clean` and `outputs/avoidance-correction-20260930/complete-source.patch`, with emphasis on UART rangefinder routing, freshness/quality, GCS/USB behavior, and the reported ELRS rate anomaly. No hardware, flash, parameter, firmware, or source mutation was performed.

## Concrete actionable finding

### ELRS telemetry-rate subtraction wraps below zero

Location: `libraries/AP_RCTelemetry/AP_CRSF_Telem.cpp`, `AP_CRSF_Telem::get_telemetry_rate()`.

Current code returns two `uint16_t` values as a direct subtraction:

```cpp
return crsf->get_link_rate(_crsf_version.protocol) - get_avg_packet_rate();
```

During link acquisition/reconnect, the smoothed measured packet rate can temporarily exceed the newly reported ELRS link rate. C++ unsigned conversion then turns a negative difference into a value near 65,536. The observed `65422` is exactly `uint16_t(-114)`, reproducing the reported diagnostic.

The value has two direct consumers:

1. the `"Telemetry rate %dHz"` GCS status message, which prints the impossible rate;
2. `is_high_speed_telemetry()` (`get_telemetry_rate() > 30`), which affects:
   - selection of high- versus low-rate scheduler periods in `update_custom_telemetry_rates()`;
   - single-packet versus packed multi-packet passthrough framing in `process_packet()`.

This can temporarily select the high-rate telemetry policy on a low/reconnecting ELRS link, reducing passthrough packing efficiency and producing misleading diagnostics. The reviewed paths do not feed this value into RC input decoding, control loops, array indices, allocation sizes, or a divisor. Therefore it is a concrete telemetry scheduling/diagnostic bug; attributing an RC-control loss, reboot, or crash to it is unsupported by this source trace.

The bug is inherited from the Copter 4.7.1 base. `AP_CRSF_Telem.cpp` is unchanged by the 13-file avoidance/rangefinder patch.

Targeted saturating correction:

```cpp
const uint16_t link_rate = crsf->get_link_rate(_crsf_version.protocol);
const uint16_t rc_rate = get_avg_packet_rate();
return link_rate > rc_rate ? link_rate - rc_rate : 0U;
```

This preserves every positive result and returns zero while the moving average is equal to or greater than the current link rate. A host check reproduced the old `50 - 164 -> 65422` result and verified that the proposed expression returns zero and keeps `is_high_speed_telemetry()` false for that case; positive cases `50 - 20 -> 30` and `100 - 20 -> 80` remain unchanged.

No existing tracked test references `get_telemetry_rate()` or `is_high_speed_telemetry()`. If the source is changed, the minimal regression table is `(link, average) -> telemetry`: `(50,164)->0`, `(50,50)->0`, `(50,49)->1`, `(50,20)->30`, `(100,20)->80`, plus the high-speed threshold checks at 30 and 31.

## Other reviewed paths

No additional concrete actionable regression was found in the requested custom-source scope:

- The configured rangefinder port compares the incoming GCS link's exact `_port` pointer with `hal.serial(id)` returned by `AP_SerialManager::get_serial_by_id()`. This is the same identity mechanism used by GCS port-number lookup.
- USB/GCS messages remain accepted by stock behavior when `MAV_PORT=-1`. With a configured physical UART, a USB-originated or null-source message is rejected as intended.
- The routing subset remains byte-identical to the previously tested six-file routing patch.
- Downward adaptive height uses the backend's packet timestamp, while stock proximity ground suppression retains its original vehicle-update timestamp. This avoids changing `PRX_IGN_GND` freshness behavior.
- MAVLink rangefinder quality mapping and the 500 ms backend timeout remain stock code. Unknown quality does not by itself invalidate the reading in this release, but the custom patch did not introduce that policy.
- Horizontal proximity dropout lifetime and the lack of an explicit AHRS velocity sample timestamp are limitations, but this review found no new code evidence that turns either into a distinct regression caused by the patch.

Existing adaptive tests were reviewed before recommending new coverage. The local unittest discovery completed 23 test methods successfully; focused native routing and boundary tests are documented separately. The only uncovered function identified by this audit is the inherited ELRS subtraction above.
