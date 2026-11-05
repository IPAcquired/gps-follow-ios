DRONE PROJECT - OWNER SOURCE CONTINUITY
Prepared November 5, 2026

This additive snapshot preserves current selected editable source beside the
existing iOS archives. It does not replace those archives or change repository
visibility, Actions configuration, installed firmware or private configuration.

READINESS
The most recent saved Orange Pi repair evidence (October 26) ended in USB boot
recovery, not confirmed normal Linux boot. The cause of the earlier H743 board
failures, exact installed FC firmware, live sensors/radio, regulator load margin,
servo commissioning and physical Follow validation remain unresolved. Software
tests/simulation are not flight clearance. Keep the aircraft grounded until
those commissioning gates have current evidence.

SOURCE LAYOUT
source/display-1.3.34: ESP32 display application, headers, assets, tests and
  platformio.ini. Target is the matching Hosyond/LCDWIKI E32R35T ST7796 display,
  ESP32-WROOM-32E. Do not use this configuration on a different display/MCU.
source/pi-current-overlay: matching current Pi Python modules and test sources.
source/pi-supporting-source: phone dashboard/web assets, projected-app assets,
  receive-only PC/H743 telemetry bridge and supporting modules.
source/pi-service-layout: nonsecret service/network helper layout.
source/pi-boot-patch: recovered atomic/unchanged-write boot patch and USB helper.
source/flight_safety_monitor: deterministic analysis/monitor source; optional
  local-model text is advisory. Applying a tuning proposal is a separate,
  deliberately guarded operation. Read its README before any execution.
source/adaptive_avoidance: custom ArduCopter patch/candidate and tests; this is
  not a full upstream firmware checkout or proof of currently installed image.
source/uwb_follow_sim: simulation and desk-model candidate, not commissioned
  autonomous Follow hardware. UWB acquisition/physical validation was unknown.
source/cad: V10 open-semicircle PETG/TPU guard STLs and generator scripts, plus
  recovered heavy-duty tray sliced 3MF and generation scripts.

EDIT / BUILD
1. Clone https://github.com/IPAcquired/gps-follow-ios.git or download Code -> ZIP.
2. Create a working branch; keep this source snapshot as a dated baseline.
3. For display compile, install trusted PlatformIO, open display-1.3.34 and
   review platformio.ini. Run: pio run -e flight_team
   The pinned espressif32 platform is 6.12.0. Library versions are in the INI.
4. A compile does not authorize flashing. No hardware build/flash occurred in
   this export. Review board/flash/partition layout and pairing preservation
   before a separate hardware procedure. The application offset in the saved
   release record is 0x10000; it is not a whole-flash image.
5. Pi source depends on Python 3, Pillow/NumPy and the original Linux/systemd,
   TLS and pairing configuration. Phone web assets and matching modules must
   move together. Do not run service installers against the wrong machine.
6. CAD generators require NumPy, manifold3d, trimesh and sometimes matplotlib.
   Historical absolute development paths need adaptation in a working copy.
   Some native tray geometry inputs are missing. The sliced 3MF is printer-
   specific and does not establish a fully reproducible parametric CAD master.
7. Review git diff/status; stage named intended files. Commit, push a branch
   and review before merging. Use git pull --ff-only before future updates.
   Do not force-push or erase history. A new git revert commit is the ordinary
   history-preserving way to undo a published change after review.

DEPENDENCIES / RECOVERY LIMITS
Current display is 1.3.34; private encrypted recovery base is 1.3.21 and needs
the current code overlay after restoration. The complete private recovery
package stays with its owner. This public repository contains no device keys,
Wi-Fi passwords, owner access secrets, encrypted private vault, raw chats,
private legal/customer records, personal inventories or model weights.
The repository cannot reconstruct a private device identity from source alone.

The original iOS workflow still consumes its pinned source ZIP at repository
root; this additive snapshot does not silently change that build target.
Unsigned iOS artifacts still need appropriate owner signing/install steps.

CHECKS PERFORMED FOR THIS SNAPSHOT
Copied source files were hashed; Python .py sources parsed; selected credential
patterns were scanned without printing values. Those checks are not a complete
security audit, a full dependency/build test or proof of hardware behavior.
No firmware build, live hardware command, account reset, history rewrite or
visibility change was performed. SOURCE-MANIFEST.json lists relative paths,
byte sizes and SHA256. Compare hashes before relying on a downloaded copy.
