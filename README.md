# Orange Pi display service inventory clock

This optional source update corrects the age of the Pi's failed-service list in the compact display API. It measures elapsed time with a monotonic clock and dates the list from the start of the system and user service checks. Normal-clock fixture snapshots taken after a two-second query reported an age of two seconds. The RC6 display reader rejected the old list at sixteen seconds.

The companion's UTC publication timestamps, the panel's packet ordering and trusted-clock checks, and the controller data sources keep their existing behavior. After a backward UTC correction an existing panel session can reject complete snapshots until its clock and ordering conditions are satisfied. Keeping the Pi's service inventory current is separate from that whole-snapshot check.

## Install on the Pi

Use the signed-in desktop owner's account. Keep the matching ZIP and its SHA-256 sidecar together. From their directory:

```sh
sha256sum -c Orange-Pi-display-service-clock-1.0.0.zip.sha256
unzip Orange-Pi-display-service-clock-1.0.0.zip -d display-service-clock-1.0.0
cd display-service-clock-1.0.0
sha256sum -c SHA256SUMS
python3 -B publisher_update.py check --live
python3 -B publisher_update.py install
python3 -B publisher_update.py check --live
```

The supported preimage is `359ed80c45cb601c6b9caa6fd4b197400815ccf6ec47fc2c8e5f135f53dc5e7a`. The qualified result is `73aa283911eced1ac5219166b3ee792be136034e6e443ebed02601a50cadfc3e`. The installer checks the exact file in the owner's bin directory and preserves its permissions. It saves the original bytes, mode and group in an owner-private recovery record. An active companion user service restarts once to import the updated module. Its clients may reconnect during that restart. An inactive service stays inactive.

The optional `--live` switch reads the existing same-user display status socket. Its report contains the age, freshness, sampling success and number of listed units. A newly started check can briefly show an unavailable inventory until its first observation completes. Use plain `check` to verify only the module hash, saved state and user service state.

## Restore

```sh
python3 -B publisher_update.py restore
python3 -B publisher_update.py check --live
```

Restoration uses the exact saved source bytes. If a local edit is detected, the installer preserves it and reports the mismatch. Keep this addendum separate from the RC6 screen and desktop fallback.

The included `fault_replay.py` can compare two local publisher files using simulated forward and backward UTC corrections. It accepts `--stock`, `--candidate`, `--out` and optional `--dependencies` for the existing companion Python modules.

