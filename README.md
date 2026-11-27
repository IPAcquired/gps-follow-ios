# Orange Pi local postflight evidence 1.0.0

The fast, balanced, quality and long profiles on the Orange Pi can now use the most recent private DataFlash summary when answering an ordinary offline AI-team question. The team captures one summary at the start of the question and shares that same version with all four profiles. They see aggregate record counts, approximate log duration, storage synchronization time and the completed totals for the active controller group.

## Read local evidence

Use the following commands from the Pi desktop owner's terminal, including a terminal shown on the ESP32 desktop.

```sh
python3 ~/bin/orangepi_postflight_evidence.py latest
python3 ~/bin/orangepi_postflight_evidence.py history
python3 ~/bin/orangepi_postflight_evidence.py show FULL-DIGEST-FROM-HISTORY
```

`latest` shows when the newest verified transfer synchronized on the Pi. This time identifies the local copy. Its capture-age category refers to the retained file. The records may predate that time or span multiple arm cycles. The current controller profile and matching digest, source receipt, saved report and byte count determine whether the snapshot can be shown. Missing or inconsistent records produce an unavailable state.

`history` lists private local handles across the snapshot and completed catalogs. `show` opens one selected report locally and returns its counts and duration. User-selected full reports, including raw observations, remain in the owner's private `~/flight-data/` tree. The four model prompts receive a fixed allowlist of numeric observations and state labels. Private handles, positions, raw log records and free-text log messages stay outside the prompt.

To ask the installed local team a question, use its existing AI Team menu or launcher and ask, for example, “How much controller log evidence is available offline? Is the newest report provisional or complete?” Replies use the model and resources available on the Pi. Reviewed owner proposals continue to use the existing approval checks and current telemetry.

## Synchronization and learning

The existing log reader checks on monitor startup or return of the native link and after a witnessed disarm. It backs off and retries if storage is unavailable. The selected controller must report fresh disarmed standby and on-ground status for file collection. Local history remains readable after disconnection or in the absence of Internet access. An idle, successful reader waits for its next trigger.

A provisional snapshot is a report on a potentially open controller file. It stays outside the completed training corpus. The completed catalog takes precedence when an identical digest later enters that corpus. Repeated questions read the existing report without producing another file transfer, training sample or policy proposal. Existing DataFlash analysis and battery/profile jobs retain their established completed-file inputs. The separate telemetry JSONL learning queue retains its own inputs.

## Setup and rollback

Install after the supported four-profile owner-review team and the postflight log intake. From the extracted bundle, run the following as the normal desktop owner. The installer checks the exact team baseline or its own installed version and saves the prior program in a private rollback directory.

```sh
sha256sum -c SHA256SUMS
python3 -B install.py check
python3 -B install.py activate
python3 ~/bin/orangepi_postflight_evidence.py latest
```

Run `python3 -B install.py rollback` from this release directory to restore the prior team entry point. Public add-ons that validate the team baseline can be installed after rolling this add-on back. Reactivation requires a compatible team version. The read-only helper remains available for any already-running team invocation.

The package tests cover all four normal prompt builders, preservation of the approved context, malformed or mismatched reports, private file permissions, symlinks, repeated digests, historical age, sanitized output, local history lookup and rollback. The installed Pi was checked with a real retained controller report and local completed history. Prompt assembly was verified without launching a new model inference.
