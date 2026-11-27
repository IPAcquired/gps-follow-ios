# Immediate review of a prepared controller plan

This addendum requires the installed field review kit v1.0.0. The existing improvement worker normally wakes about every 15 minutes. A newly prepared controller plan also expires after 15 minutes. This watcher gives the worker an opportunity to begin the review as soon as the plan arrives.

As the signed-in desktop owner, extract the addendum and run the installer from that directory.

```sh
python3 -B install_wake.py install
systemctl --user is-active orangepi-controller-review.path
```

Prepare the plan directly in `~/.local/state/corvon-maintenance/proposals/` with the existing maintenance tool. The original file path and contents are bound to its digest. The watcher wakes the existing AI-improvement service when the directory changes. That service validates the plan and the controller evidence and checks whether the Pi has enough resources to review it. Review decisions remain in the existing queue. Use **Field Change Review** on the signed-in desktop to inspect the proposal and record your choice.

An occupied model, unavailable telemetry, heavy load, an expired plan or a missing vote can keep a proposal pending. The existing timer provides another opportunity to review a still-valid proposal. Prepare a fresh plan after expiry. The manual review command in the main kit remains available.

To remove the watcher, run the following from the same extracted directory.

```sh
python3 -B install_wake.py rollback
```
