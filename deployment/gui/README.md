# WEAVE CBT Desktop Manager

Native desktop software for Windows and Linux, built with Python/PySide6. The existing `weave` CLI remains the sole controller for CBT installation, lifecycle operations, diagnostics and logs.

## How schools install

**Windows:** Download the single `WEAVE-CBT-Staging-Desktop-Setup.exe` from the matched staging GitHub Release (or `WEAVE-CBT-Desktop-Setup.exe` for production). Run the **native Windows setup wizard**. It checks whether the CLI and CBT server already exist, verifies the installation channel, installs the bundled GUI and matching CLI to `C:\Program Files\WeaveCBT`, creates Start Menu/optional desktop shortcuts, and can launch the manager as the original user after UAC installation. No ZIP extraction, Python installation, GitHub login, or manual CLI command is needed. The desktop installer never modifies the exam database or installs the CBT server without explicit user action.

**Linux (Ubuntu/Debian amd64):** Download and open the `weave-cbt-desktop-staging-linux-amd64.deb` package in a graphical package installer, or install via `apt`. This installs both the native GUI and matching CLI. Opening `WEAVE CBT Desktop Manager` provides the same guided first-run onboarding.

The three-step first-use wizard introduces WEAVE, detects the verified existing CLI separately from installed CBT server state, then opens the manager's **Install WEAVE CBT** page. The user starts the actual CBT install explicitly; CLI output streams to the application asynchronously. On Windows, CLI install exit code 10 signals that Windows requires reboot before resuming.

For Linux, Polkit authorization is used to run privileged CLI commands. For Windows, UAC prompts only when an administrative operation is requested. School exams continue running when the GUI is closed.

## Developing locally

```bash
python -m pip install 'PySide6>=6.7,<7'
python deployment/gui/main.py
QT_QPA_PLATFORM=offscreen python deployment/gui/main.py --smoke-test
```

The compiled executable includes the exact uploaded WEAVE logo recolored with the standard blue palette. Building the GUI is separate from generating a distributable setup wizard; release CI handles both. CI also verifies a fresh-installed GUI and CLI on Windows and Linux, the immutable digest-pinned release manifest, and includes SHA256SUMS for all release packages.

**Safety:** Staging never silently overwrites a production manager. Existing examination records in the data directory are not removed by desktop setup. An unknown/legacy CLI installation without a valid manifest must be repaired or migrated before it can be overwritten. The Windows desktop uninstaller leaves the CLI and assets in place so uninstalling the GUI does not strand an existing CBT server. Hands-on Windows WSL reboot, actual LAN student connectivity and Linux desktop Polkit flows still require acceptance testing on supported school machines.
