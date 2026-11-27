# Field change review

On the signed-in Orange Pi desktop, open **Applications → Settings → Field change review**. The optional paired ESP32 touchscreen shows the same desktop and accepts the same button actions. A mouse connected directly to the Pi can also make the decision. The window scales its controls when the Pi desktop is larger than the field screen.

Choose a controller telemetry or AI policy proposal to see the current and proposed values, reason, four local model verdicts, expiration and SHA-256. If a review is missing, choose **Request local model review**, then **Recheck review**. The models must approve the same current proposal and the Pi must verify the current operating conditions before **Approve digest** becomes available. Unsupported controller settings require manual review.

- **Approve digest** opens a confirmation displaying the full SHA-256. Confirming rechecks the proposal and records an owner-only decision. An approval alone leaves the settings staged.
- **Decline** records the decision for these exact bytes and retains the proposal for inspection.
- **Later** returns to the queue. It records no decision.

For an approved local AI policy, **Apply approved policy** invokes the installed policy tool with that exact digest. For an approved change to the allowlisted controller telemetry profile over native UART, use the foreground terminal command shown in the review. It requires the signed-in owner, interactive confirmation and existing administrator authorization, and revalidates the current model review before handing off to the existing maintenance tool. That tool independently checks board identity, pre-state, freshness, ground state and its exact proposal digest. A separate USB connection or rollback requires the owner's matching port or journal. The window does not provide an actuator, flight-mode or firmware writer.

## Installation

The existing paired desktop, GTK 3 with Python GObject bindings, maintenance tools and local model review module must already be installed. Sign in as the ordinary desktop owner and run `python3 -B install.py` from this directory. To enable a desktop notification for each newly staged proposal on future logins, add `--notifications`. The optional notifier uses `notify-send`. The launcher is also available at `~/.local/bin/orangepi-field-review`.

Prepare a controller proposal directly under `~/.local/state/corvon-maintenance/proposals/` with the installed maintenance tool. Its digest binds it to its original path. The existing AI policy queue is `~/ai-improvement/pending/`. Decisions live under `~/.local/state/corvon-maintenance/owner-decisions/` with owner-only permissions. The software works with the Pi's local queues and does not require an internet connection.

Run `python3 -B install.py --rollback` with the same owner account to restore the exact prior review launcher, desktop entries and application files. Rollback preserves proposals and owner decisions. The installer holds if one of its application files was edited independently.
