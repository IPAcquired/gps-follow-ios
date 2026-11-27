# Orange Pi offline field change review

This update adds a touchscreen-friendly decision window and local model review to an existing CORVON companion installation. Open **Applications → Settings → Field change review** on the signed-in Orange Pi desktop or its paired ESP32 field screen. The window shows the old and proposed values, the reason for each proposal, the current model decisions and the exact digest submitted to the owner.

## Install offline

Use the current desktop owner's account. The Pi needs its existing CORVON maintenance kit, AI team and policy tools, three installed model weights, a functioning controller monitor, Python 3 and GTK 3 Python bindings. Keep the extracted update in one directory. Run from its root.

```sh
sha256sum -c SHA256SUMS &&
python3 -B model/install_model_review.py stage &&
python3 -B model/install_model_review.py activate &&
python3 -B ui/install.py
```

For optional notifications about newly pending proposals, run `python3 -B ui/install.py --notifications`. It enables a local desktop notifier on the next login. The update includes no model weights or device-specific setup.

## Decide in the field

Open a proposal and inspect each change. The four required local profiles must approve the same digest. A missed vote, model rejection, changed proposal, stale or mismatched telemetry, or a configured hosted-review requirement that cannot be satisfied keeps approval on hold.

**Approve digest** asks the signed-in owner to confirm the full SHA-256 and saves a private decision. **Decline** retains the proposal and its decision. **Later** leaves it staged. A fresh decision is required after the original approval expires. Approving a digest does not itself apply the change.

An approved local AI policy can be applied by a separate explicit action. An approved native-UART telemetry-profile plan can be handed to the existing guarded maintenance tool from a foreground terminal with the owner's existing administrator authorization. That tool rechecks the connected board, ground state, pre-state, journal and exact proposal. Other flight parameters, firmware, USB-route adjustments and recovery operations require their existing manual procedures.

Follow the [operator guide](ui/README.md) for the queues, buttons, handoff and local file locations. The [model review guide](model/MODEL-REVIEW.md) lists the four profiles and the conditions that hold a proposal.

## Roll back

Close the review window and run the commands below from this package as the same owner. They restore the previous application files and AI entry points. Local decisions, proposals and review receipts remain private on the Pi.

```sh
python3 -B ui/install.py --rollback &&
python3 -B model/install_model_review.py rollback
```
