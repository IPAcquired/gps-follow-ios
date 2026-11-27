# Offline field change review 1.0.0

- Added a local owner decision window that works on the Orange Pi desktop and its paired ESP32 touchscreen. The current and proposed values, reason, model status, expiry and exact SHA-256 are visible before consent.
- Added sequential offline review using the configured fast, balanced, quality and long-context profiles across three local model weights. Unavailable or incomplete review, stale evidence and an unmet hosted-review requirement keep the proposal pending.
- Added durable owner-only decisions bound to a proposal digest. Confirming approval rechecks current eligibility. Applying a policy or handing off an allowed telemetry adjustment is a separate action through the existing guarded tools. Unsupported flight changes require manual review.
- Added owner-local installers and rollback, pending-only desktop notifications and tests for expired approvals, competing clicks, rejected votes, guarded handoff and installation recovery.
