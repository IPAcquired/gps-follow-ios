# Directional adaptive avoidance prototype

This is a **default-off firmware extension, now installed and enabled on this controller** for ArduCopter 4.7.1.

Independent review rejected a Lua design that changed the global `AVOID_MARGIN`: that would enlarge unrelated directions, affect vertical obstacles, remain visible to other parameter consumers, and risk overwriting an operator change. The final candidate is the C++ patch in `arducopter-4.7.1-directional-adaptive-margin.patch`.

The patch leaves the live baseline (`AVOID_MARGIN`, currently 1.0 m) untouched and computes an effective margin separately for each fresh horizontal obstacle:

`effective = live baseline + min(max(actual body velocity · obstacle direction, 0) × 0.35 s, 1.0 m)`

ArduPilot's existing stopping-distance term remains unchanged and separate. There is no second `v²/(2a)` term. A healthy, tilt-corrected downward rangefinder sample whose actual backend receipt time is no older than 500 ms adds 0.15 m of horizontal side clearance below 1.5 m, released above 1.8 m; an invalid or stale downward sample suppresses only that addition. This is not floor avoidance or terrain following.

Growth is immediate beyond a 0.05 m hysteresis. Reduction is limited to 0.5 m/s in eight body-frame sectors. Invalid, non-finite, unhealthy, or GPS-glitching estimator velocity uses the configured maximum reaction allowance for a fresh obstacle; the AHRS API does not expose sample age, so this does not claim detection of a frozen estimate that remains marked healthy. Stale obstacles are removed by the existing `AP_Proximity` path. Adaptive clearance changes braking and velocity limiting only; native back-away remains tied to the 1 m baseline. The patch logs `ADPM` with live baseline, effective margin, closing speed, downward altitude, sector, and validity.

`AVOID_ADAP_EN` defaults to zero and is latched once during vehicle initialization after parameters load; changing it requires a reboot. Each new arm epoch, disabling proximity avoidance, disarming, or suspending updates for more than one second clears all transient sector state. With it disabled, the stock baseline is used. The installed candidate leaves the saved 1.0 m margin unchanged.

Coverage remains limited to the real front, left, and right sensors. There is no rear or guaranteed diagonal coverage. AltHold uses a different distance-to-lean avoidance path, so this patch does not claim the same adaptive behavior there. A larger margin does not guarantee clearance, and this is not a high-speed avoidance solution.

Validation levels are reported separately: deterministic formula/scenario tests; focused compilation of the actual `AC_Avoidance` object; isolated SITL startup or vehicle/obstacle dynamics when the repository permits it; and later props-off sensor-direction and staged flight testing.

## Current verified candidate

The complete current source patch is SHA-256 `a711637b05257fba23bbf1c0102fd371c2f9a0a334e183a7fb4bbe4823571a36`. It includes the full existing UART-routing patch and the corrected proximity-boundary ownership guard. The guard prevents side updates and sensor invalidation from pushing a surviving sensor boundary outward; it applies independently of the adaptive-enable setting.

The final integrated simulator passed Guided and Loiter fixed-world-wall tests using the RangeFinder backend and a 5 Hz proximity filter. Minimum gaps were approximately 1.098 m and 1.138 m respectively. Both used a nominal 2 m/s approach profile; Loiter's actual peak was 2.399 m/s. Full details, hashes, limitations and current installation state are in `../outputs/avoidance-correction-20260930/README.md`.

Installation completed through DFU after the serial transition failed without erasing anything. The application passed full read-back; bootloader and saved storage were unchanged. The three intended settings were acknowledged and survived a proven reboot. The later powered capture passed pre-arm checks, radio health and all four sensor streams after the left field of view was cleared; the earlier warnings remain in the historical captures. The follow-up audit in `../outputs/h743-followup-audit-20260930/README.md` records the remaining sensor-loss and ELRS rate-arithmetic limitations. This is not flight clearance. Earlier candidate artifacts are superseded.

The installed build has `AP_AVOIDANCE_ALTHOLD_ENABLED=0`: SE does not enable horizontal obstacle avoidance in AltHold. Loiter is the tested mode for this adaptive velocity-limiting feature.
