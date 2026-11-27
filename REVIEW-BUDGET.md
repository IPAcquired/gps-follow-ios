# Resource limits for offline maintenance reviews

The two 4B profiles previously used all eight CPU threads during a proposal review. This addendum runs each of them sequentially with two inference threads and a CPU limit equivalent to one and a half cores. Quality keeps its 8,192-token context and uses 256-token batches with 64-token microbatches to reduce memory pressure. Long keeps its 12,288-token context and its existing batch settings.

The normal model services, their weights, and the existing approval rules are preserved. A review takes the existing shared model lock, sets the temporary service limits, and restores the original settings afterward. An independent watcher detects an interrupted reviewer and performs the same recovery. The existing telemetry, memory, temperature and expiry checks can defer any review. An abstention leaves a proposal pending.

## Install and remove the addendum

Start with field review v1.0.0 installed. If you also use the v1.0.1 proposal watcher, install that watcher first. It can run independently. From the resource-budget ZIP's extracted directory, run the following as the signed-in desktop owner.

```sh
python3 -B install_budget.py install
```

The existing **Field Change Review** workflow and model-review commands pick up the limits on their next run. If another model or an interrupted review owns the lock, try again after it completes. The installer stores a private, checksum-verified copy of the original review module and refuses an unrecognized local edit.

To restore the original review implementation, run the following from the same extracted ZIP.

```sh
python3 -B install_budget.py rollback
```

## Verification

The actual quality and long profiles each completed a separate local inference using fresh disarmed telemetry under these resource settings. Both returned an abstention for the diagnostic. Each attempt restored the resident fast model. Those evidence checks do not authorize an update. The included tests use lightweight service fixtures to check the kernel CPU limit, thread and batch settings, interruption recovery, exact installation, rollback and preservation of local edits. A systemd user manager is required for the service test.
