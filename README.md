# Orange Pi owner field tools

Two optional tools run under the signed-in Pi desktop owner. The Field terminal adds an Xfce application menu entry. The field-review layout update adjusts the existing GTK window for smaller screens and orientation changes. Each tool has its own installer and rollback. Close any open Field change review window before updating its layout.

## Open the kit on the Pi

Download the ZIP and its adjacent checksum sidecar from this release. From their download directory, run the following commands in a local terminal.

```sh
sha256sum -c Orange-Pi-owner-field-tools-1.0.0.zip.sha256
unzip Orange-Pi-owner-field-tools-1.0.0.zip -d owner-field-tools-1.0.0
cd owner-field-tools-1.0.0
sha256sum -c SHA256SUMS
```

If the Pi has no terminal emulator yet, save both downloads in the owner's Downloads directory and use the Xfce file manager to extract the ZIP to `Downloads/owner-field-tools-1.0.0`. Press **Alt+F2** on the local Pi desktop and enter this single command. It checks the downloaded ZIP and the extracted files before opening the staged graphical test and installing the terminal. The directory names must match your download location.

```sh
/bin/sh -c 'cd "$HOME/Downloads" && sha256sum -c Orange-Pi-owner-field-tools-1.0.0.zip.sha256 && cd owner-field-tools-1.0.0 && sha256sum -c SHA256SUMS && exec /usr/bin/python3 -B owner_terminal.py install --gui'
```

## Field terminal

First installation requires Python 3, the distribution's Python APT bindings, dpkg, compatible installed system libraries, and access to the exact official package versions in the Pi's existing package indexes. The installer downloads xterm and libutempter0, verifies each archive against the trusted distribution index, and keeps the terminal, its library and the two copyright notices under the owner's home directory. The optional graphical test opens a temporary iconic X11 terminal and checks the shell's pseudo-terminal. Run it from the active graphical owner session.

```sh
/usr/bin/python3 -B owner_terminal.py install --gui
/usr/bin/python3 -B owner_terminal.py status
```

Launch **Applications > System > Field terminal**. It uses the current X11 desktop dimensions at launch and chooses a readable default size. If the Pi has no compatible X11 session at installation time, use `probe` for a staging-only package and linker check. Once installed, the terminal can run offline.

```sh
/usr/bin/python3 -B owner_terminal.py remove
```

Removal checks the saved hashes before deleting the owner-local payload and launchers. If an earlier private test revision is installed, use this same remove command before installing the current launcher.

## Field-review window

The layout update requires the original GTK source from the existing field-review 1.0.0 installation. It checks that source and reconstructs the tested GTK file locally. It saves the previous GTK bytes, file mode and upstream rollback journal under the owner's existing installer state. A changed original is reported before replacement.

```sh
/usr/bin/python3 -B install_layout.py install
/usr/bin/python3 -B install_layout.py status
```

Open **Applications > Settings > Field change review**. Close and reopen an existing window to pick up the new layout. Restore the prior GTK file and original installer journal using the extracted kit.

```sh
/usr/bin/python3 -B install_layout.py rollback
```

Both installers run as the ordinary owner. The separate field-review worker and the paired RC6 display release have their own installation and recovery instructions. [Original field-review release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/orangepi-field-change-review-v1.0.0) | [RC6 display release](https://github.com/IPAcquired/gps-follow-ios/releases/tag/wired-field-console-r3.4-rc6)

