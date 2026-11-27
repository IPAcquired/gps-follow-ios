# 1.0.0

The Orange Pi now starts a guarded log acquisition check on its selected native controller link at startup and after a witnessed disarm. It records the current landed state, downloads stable DataFlash files and feeds closed logs into the existing analyzer. A separate summary for an open controller log gives the owner postflight results while the controller continues using that file. Content-based deduplication protects the historical profile.

Accepted telemetry updates now publish at a 100 ms target. The monitor identifies the provenance of observed telemetry and reports the very limited read-query capabilities of its background job. Existing protected desktop and approval checks resume their passive state when the queries finish.

The supported baseline requires the known CORVON companion monitor and three existing analyzer modules. The installer verifies all four. See the operating guide for service commands, the read-only mounted card route, limits and rollback. Live transfers depend on an available FC storage volume. The USB or FIFO PC telemetry bridge supplies receive-only telemetry.
