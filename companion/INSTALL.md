# Install the maintenance tools on the Orange Pi

This kit runs on the Orange Pi Zero 3W used with the CORVON743V2 project. It expects the existing telemetry monitor, the native UART0 alias `/dev/h743`, and the project's Python environment. Installation adds foreground tools. The existing telemetry service continues to own the UART during ordinary operation.

1. Download the companion ZIP and `SHA256SUMS.txt` from the same GitHub release. From the download directory, verify the ZIP against its entry in that file. A checksum from the same download verifies integrity; use the project's published GitHub release as the trusted source.
2. Extract the ZIP into a new directory owned by the operator. From that directory, run the offline tests and the dependency check.

   ```sh
   /opt/drone/venv/bin/python -B -m unittest discover -v
   /opt/drone/venv/bin/python -B companion_maintenance.py check
   ```

3. Install the reviewed files in a root-owned directory. Use the exact filenames from this release. The journal, approval proposals and device backups belong in a private directory owned by the companion account.

   ```sh
   kit=/usr/local/lib/corvon-maintenance
   sudo install -d -o root -g root -m 0755 "$kit"
   sudo install -o root -g root -m 0644 \
     companion_maintenance.py corvon_firmware.py uart_handoff.py \
     CORVON743V2-4.7.3-R2.abin release-manifest.json \
     README.md FIRMWARE.md INSTALL.md COPYING.txt \
     test_companion_maintenance.py test_corvon_firmware.py test_uart_handoff.py "$kit/"
   /opt/drone/venv/bin/python -B "$kit/companion_maintenance.py" check
   ```

4. Run `python3 "$kit/companion_maintenance.py" monitor`. Check that the status is fresh and shows the expected route and arm state. The existing Windows Companion remains the interface for its dashboard, camera, sensor and learning-policy views.
5. Follow [Review an adjustment](README.md) to audit the actual controller, save a proposal, review the before and after values, and approve its digest. [Approved firmware updates](FIRMWARE.md) covers the separate SD update and verification process. Use a fresh transaction directory for each firmware proposal.

When replacing an existing installation, finish any active maintenance session, preserve its private recovery files and keep the previous version available. Run the new kit's local checks before switching the installed version. Changes to the existing monitor service configuration are outside this installation procedure.
