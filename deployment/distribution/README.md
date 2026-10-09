# WEAVE CBT terminal installers

Windows release: `WEAVE-CBT-Setup.exe` is a console application, not a
graphical wizard. It embeds compiled `weave.exe`, versioned deployment assets,
and an environment-specific release manifest. Double-clicking opens a console;
running it in PowerShell works without extra flags. The setup copies into
`C:\Program Files\WeaveCBT`, registers machine PATH, and prints the next command:
`weave install` in a NEW elevated PowerShell.

Linux release: tar.gz contains `weave`, `assets`, and `install.sh`.
After extraction run `sudo ./install.sh`, then `sudo weave install`.

Only the CLI manager is bundled. Windows Ubuntu WSL rootfs and Docker,
plus WEAVE container images, are fetched by `weave install` over the network.
The official release manifest must pin an immutable GHCR image digest.

Important: Current Windows WSL persistence relies on an interactive logon
task. Do not advertise unattended availability before sign-in/after sign-out
until a Windows boot persistence solution has passed real-machine testing.
