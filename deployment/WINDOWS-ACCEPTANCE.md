# WEAVE CBT — Windows desktop and server acceptance checklist

These checks must be performed on freshly installed, supported AMD64 Windows
10/11 and Windows Server 2022/2025 machines before a Production installer is
declared ready. They are not replacements for GitHub Actions syntax tests.

## 1. Install the standalone CLI Manager

Download the correct channel's Windows Setup EXE from the WEAVE frontend.
Double-click it from File Explorer or execute it from an elevated PowerShell:

    .\WEAVE-CBT-Setup.exe

Setup must display terminal colors, install the CLI/assets under Program
Files, register machine PATH, and print the next operation. In a NEW
elevated Windows PowerShell 5.1 session, confirm:

    Get-Command weave
    weave --help
    weave install

Do not copy the setup executable to another directory. Verify that UAC denial
shows an actionable error and does not modify the machine.

## 2. Confirm official Microsoft WSL prerequisites

    Get-CimInstance Win32_OperatingSystem | Select-Object Caption, BuildNumber
    Get-CimInstance Win32_Processor | Select-Object VirtualizationFirmwareEnabled
    Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux
    Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    wsl.exe --status
    wsl.exe --version

On a fresh machine, `weave install` must call Microsoft's supported WSL
installation/updating commands, save a reboot checkpoint, and return code
3010 to its Windows bootstrap when a reboot is required. The CLI reports
that requirement using its dedicated exit code 10. Only the operator should
restart Windows, then open elevated PowerShell and repeat `weave install`.
Verify the same local credentials are preserved across the restart.

Windows Server 2019 is not a supported WSL2 host for this version. Cloud VMs
must expose nested virtualization. Microsoft WSL systemd support requires a
modern WSL release; `wsl.exe --version` is checked before Ubuntu import.

## 3. Verify Ubuntu and Docker Engine

    wsl.exe --list --verbose
    wsl.exe --distribution WeaveCBT --user root -- cat /etc/os-release
    wsl.exe --distribution WeaveCBT --user root -- cat /proc/1/comm
    wsl.exe --distribution WeaveCBT --user root -- docker info
    wsl.exe --distribution WeaveCBT --user root -- docker compose version

The distro must be named WeaveCBT, use WSL version 2, and be Ubuntu 24.04.
PID 1 must be systemd. Check the Canonical rootfs SHA-256 verification message.
Ensure Docker downloads retry stalled transfers, preserve cached packages,
and never interrupt dpkg. Retry after disabling network access mid-download;
already completed installation stages must remain safe to reuse.

## 4. Verify local and LAN access

From the **Windows host** in PowerShell 5.1:

    Test-NetConnection -ComputerName localhost -Port 80
    Invoke-WebRequest -Uri http://localhost/staff -UseBasicParsing
    Get-NetConnectionProfile
    netsh interface portproxy show v4tov4

From a **different device on the same trusted school LAN**, browse to the
Windows host's LAN IPv4 address (for example, http://192.168.x.x/staff).
Do not assume success on localhost means students can connect.

Microsoft documents that default WSL2 NAT requires host-to-WSL routing.
The CLI supports an explicit, administrator-approved private-network setup:

    weave lan --listen-address 192.168.1.24 --client-subnet 192.168.1.0/24
    weave lan --refresh

Use the actual host IPv4 and the narrowest trusted school subnet. Confirm
the Windows network category is Private or DomainAuthenticated. Verify
`netsh interface portproxy show v4tov4` contains only the intended host
listener and WSL destination. Confirm the WEAVE CBT TCP/80 inbound rule
permits only the selected address/subnet, then test from a DIFFERENT PC.

After a host reboot and interactive sign-in, verify that the scheduled WSL
keeper refreshes a changed NAT destination. Verify `weave start` and
`weave restart` reconcile stale addresses. Test collision protection by
using an unrelated existing portproxy on a disposable test VM.

To change network, run `weave lan --remove` before selecting a new scope.
Mirrored mode, VPN routing, before-login hosting, and sign-out persistence
are not guaranteed. Do not configure Internet-wide firewall access.

## 5. Restart, sign-out, and data persistence

    weave doctor
    weave status
    weave stop
    weave start

Confirm students are not taking exams before any restart/power test. Verify
WEAVE's Docker volumes, PostgreSQL exam data, and runtime.env survive system
reboot and the supported update/rollback operations.

Current Windows WSL keeping is tied to the installation owner's interactive
logon. A real Server Core/remote sign-out test is mandatory before advertising
24/7, no-user-login Windows server hosting. Until then the known limitation
must remain visible in release documentation.

## 6. Ordinary Windows laptops and desktops

Confirm that CBT still responds during the intended exam window while the
hosting machine is connected to AC power and its display is locked. A Windows
laptop must not automatically sleep when its lid closes or when idle;
otherwise Docker and exams may become unavailable. Verify the relevant power
settings on the host rather than changing every school administrator's global
power plan silently. Prefer wired Ethernet to unstable Wi-Fi for busy labs.

## 7. Package release acceptance

On the staging build verify the compiled EXE with `--verify-payload` before
installation, plus actual installation on a fresh Windows VM and a physical
Windows laptop. Confirm paths containing spaces, PATH in a newly opened
PowerShell session, UAC decline behavior, safe repeated setup, and color
presentation. Code-sign Production installers before broad customer delivery.

Reference: https://learn.microsoft.com/en-us/windows/wsl/networking
