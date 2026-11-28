# Native telemetry display changes

The overview and sensor cards update changed text and side indicators in landscape and portrait. Numeric details use one coherent publication per visible page. Previously accepted readings keep their original expiry when a producer is briefly busy. Rejected publications clear prior sensor indications. Native raw channels and ranges require a current controller heartbeat, and an invalid fault inventory shows an unavailable report.

The package includes the exact RC6 rollback app, partition reference, application source, release checksums and guarded screen updater. The binary and baseline hashes are recorded in `firmware/provenance.json`. The synthetic updater tests use memory-backed devices and can be run on Linux with `python3 -B test_screen_update.py`.
