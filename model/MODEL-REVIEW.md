# Offline model review

The Orange Pi can review a prepared telemetry-profile change or a proposed local AI policy. The controller monitor remains the sole receiver on its telemetry port. Each language-model reviewer sees the most recent matching heartbeat, disarm state, flight mode, system status and available GPS fix quality. Model prompts omit coordinates, status-message text, device identifiers and pairing material. A missing landed-state report is marked unknown.

The installed team runs four profiles sequentially on three sets of language-model weights. Fast uses 0.5B, balanced uses 2B, and quality and long-context each use the same 4B weights with their respective configurations. Every required profile must return an affirmative decision. A later profile sees the earlier structured votes. Independent source, proposal checksum and deterministic evaluation checks remain in force. The vision detector, projector weights and learned battery predictors produce observations for their own tasks. They do not evaluate language proposals.

## Install or roll back

Use the Pi's existing desktop-owner account. From the directory containing the installer, run:

```sh
python3 -B install_model_review.py stage
python3 -B install_model_review.py activate
```

The installer checks the original AI entry points before preparing a private backup under `~/.local/share/orangepi-model-review-update`. A running model job holds the shared lock. Retry after it finishes. To restore the previous files, use the same package:

```sh
python3 -B install_model_review.py rollback
```

## Review an update

The existing AI-improvement timer checks the existing pending queue and the owner's controller proposals directory. Save a controller proposal directly to `~/.local/state/corvon-maintenance/proposals/` when the maintenance tool first prepares it. The original path and SHA-256 are bound to the proposal. A new proposal is required if the controller plan expires or its contents change.

For an immediate review in the field:

```sh
~/bin/orangepi-ai-team --review-kind controller --review-proposal "$proposal" --review-sha256 "$digest"
```

Use the original maintenance output for the file and digest. For a local prompt or sampling-policy update, use `--review-kind ai-policy`, the pending file in `~/ai-improvement/pending/`, and that record's `approval_sha256`. The review requires fresh matching disarmed standby telemetry and checks the performance guard while loading and running the models. A failed or missing vote, stale source, changed model file, expired plan or unavailable reviewer keeps the proposal ineligible.

Use **Field Change Review** on the signed-in desktop through the ESP32 to inspect each difference, its reason and the model votes. Choose **Approve**, **Decline** or **Later**. The exact owner decision and the model review remain separate. A model vote performs no controller write. The maintenance tool rechecks the controller state, proposal and safeguards during a separate guarded operation.

## Test the models without proposing an update

```sh
~/bin/orangepi-ai-team --check-local-review --budget-seconds 720
```

This diagnostic checks whether the live monitor supports its own disarmed-standby report. Each model can approve, abstain or reject independently. The command returns the active model service to its prior configuration and issues no update approval. Model loading from an SD card can take several minutes. Local diagnostic and proposal attempts remain in `~/.local/state/orangepi-ai-team/proposal-reviews/`. Treat these receipts as private.

Jev is a hosted advisor. To mark Jev as mandatory for selected types of proposal, use the owner-only `~/.config/orangepi-companion/model-review-policy.json` file with permissions 0600:

```json
{"schema":1,"require_jev_for":["controller"]}
```

A proposal with that requirement stays pending offline. This reviewer makes no external model requests. A local unanimous vote cannot satisfy an external-review requirement.
