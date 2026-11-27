# Guarded keyboard on the paired display

This component accompanies the R3.2 Pi sender and touchscreen. The installed Companion must already provide its matching-controller ground guard, protected Unix desktop socket, input allowlist, and accessibility focus monitor. The paired sender also checks the active local owner's lock state.

Review the included broker source against the installed owner's version. Apply the native-key mapping to a staging copy with the following command.

    python3 apply_input.py PATH_TO_COMPANION STAGED_OUTPUT

Place the staged output beside the broker under the name orangepi-companion. Run the tests in that directory.

    python3 -B -m unittest -q test_wired_focus

The service needs Python 3, xdotool, its desktop_focus module and the active owner's local X11 authority file. For the accompanying archived-log update, run the following against the staged Companion after the main CORVON source overlay. It verifies evidence against the exact active profile.

    python3 apply_cached_review.py STAGED_COMPANION NEW_STAGED_OUTPUT

Use the new staged output as orangepi-companion and run both test_wired_focus and test_current_log_review. Install the reviewed files through the project's owner deployment procedure. Keep a recovery copy before restarting the owner's Companion interface. Tap an editable field on a test window, open Keyboard, and check text, Backspace, an arrow, and Enter.

The focus action runs behind the same Unix peer and owner lease checks as desktop input. It returns an opaque revision for the selected X11 window and accessibility focus state. Each focused text or key request supplies that revision. A changed revision rejects the input and prompts the operator to select the field again. Applications that do not report accessibility focus use the focused X11 window. The broker reads window identifiers and focus state only.
