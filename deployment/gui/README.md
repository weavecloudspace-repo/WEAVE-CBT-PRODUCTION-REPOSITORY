# WEAVE CBT Desktop Manager (Windows and Linux)

PySide6 + Qt Widgets desktop front end to the existing, authoritative WEAVE CBT CLI.
Run locally with:
\`\`\`bash
python -m pip install PySide6
python deployment/gui/main.py
\`\`\`

The desktop manager discovers, in order, the canonical globally installed CLI,
an executable on PATH, and a packaged CLI. It validates the manager with
\`weave release\`. It independently checks the canonical installation state
(\`C:\\ProgramData\\WeaveCBT\\install.json\` on Windows or
\`/var/lib/weave-cbt/install.json\` on Linux), its schema and installed files.
Discovering the manager does not imply the CBT server is installed.

The GUI invokes **only** existing CLI operations; it never modifies Docker, WSL
or the school database itself. Output is collected asynchronously through
QProcess and bounded in memory. A CLI install exit code 10 means the user
must reboot Windows and reopen the manager to resume. Updates, rollback,
uninstall and LAN configuration are intentionally not exposed as buttons
until their destructive and network/security confirmation flows are implemented.

For privileged operations, the current GUI requests explicit elevation and
relaunches itself with UAC on Windows or pkexec on Linux. This is a *first
iteration*: the long-term model should be a signed, narrow privileged helper
and an unprivileged Qt window communicating over authenticated local IPC.

The logo asset must be derived from the user's supplied image by **pixel-only
blue recoloring** (no recreation of its geometry).

The CI release workflow is responsible for bundling the CLI, application
assets, and this desktop interface. CI compilation/smoke tests are not a
substitute for manual Windows/WSL fresh-install, reboot and LAN testing.
