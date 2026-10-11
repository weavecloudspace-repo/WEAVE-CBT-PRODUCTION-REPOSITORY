# WEAVE deployment tooling

## V1 release and installation architecture

All branches run backend, frontend, CLI and platform bootstrap tests. Only
`staging` and `master` build or publish Docker images and compiled CLI
manager installers. Staging publishes prereleases automatically. A push
to `master` validates/builds but **does not publish a Production GitHub Release**:
select GitHub Actions > WEAVE CBT image > Run workflow on `master`, and set
`approve_production=true` to authorize production promotion. Docker image and
Windows/Linux CLI compilation run concurrently; final installers wait for the
published immutable image digest. GitHub Actions also verifies that the GHCR
image is publicly retrievable without a registry login before publishing an
installer, because schools should not need GitHub credentials.

Each official release contains a digest-pinned CBT application image and
matched Windows and Linux CLI packages from the same commit. The Windows
`WEAVE-CBT-Setup.exe` is a colored **console** application, not a wizard.
It installs the WEAVE manager into Program Files, safely registers PATH,
and prints the exact next command: open a NEW elevated PowerShell and run
`weave install`. Double-clicking the Setup EXE also opens a console.

On Linux, extract the official tar.gz, run `sudo ./install.sh`, then
`sudo weave install` from any directory. Packaged releases ship Compose,
Nginx, and OS bootstrap assets with the correct channel manifest.
`weave install` reads its embedded WEAVE API URL and digest-pinned image,
generates secure database credentials, and no longer requires explicit
`--assets-dir`, `--env-file` or `--rootfs-archive` for normal installations.

GitHub Actions verifies the compiled Windows setup with `--verify-payload`
before publishing. This self-test checks the embedded `weave.exe` and manifest
without requesting administrator privileges or altering machine state.
The Linux job extracts its package and runs the compiled `weave --help`.

## Windows WSL and Docker reliability

The Windows bootstrap uses supported Microsoft WSL install/update commands
and checks for WSL systemd support (0.67.6+). Windows prerequisites are
enabled without an unexpected reboot. If restart is required, the bootstrap
records its state, exits 3010 and directs the administrator to reboot and
rerun `weave install`. It downloads the official Canonical Ubuntu 24.04
AMD64 WSL rootfs over HTTPS and verifies the release-pinned SHA-256 digest.
Downloads have bounded attempts and can resume, where supported.

Docker package downloads use an inactivity watchdog and controlled retries
without interrupting dpkg configuration. Docker Compose image pulls stream
progress and fail/retry on inactivity or overall timeout.

Current Windows baseline: compatible Windows 10/11, Windows Server 2022/2025,
AMD64 hardware, WSL2 virtualization, and Windows PowerShell 5.1. Windows
Server 2019 is outside the current WSL2 support matrix.

IMPORTANT: A passing Windows CI syntax/test runner does not prove that a
fresh machine can install WSL2 and Docker. The current WSL persistence task
requires an interactive sign-in and does not guarantee hosting before login
or after sign-out. Windows firewall, WSL networking, LAN reachability, and
fresh-machine boot/reboot behavior require actual Windows acceptance testing.
Do not advertise unattended Windows availability until those tests pass.

## Opt-in school LAN access on Windows

Windows WSL2 NAT is not automatically reachable from other computers on the
school LAN. After `weave install` completes, an administrator can enable a
narrowly scoped TCP/80 listener on a **specific private Windows LAN IPv4**:

```powershell
weave lan --listen-address 192.168.1.24 --client-subnet 192.168.1.0/24
weave lan --refresh
```

Use the actual Windows host IP and smallest appropriate trusted school subnet;
do not copy the example addresses verbatim. The command refuses public/wildcard
listeners, public or overly broad subnets, non-Private/Domain host connections,
unrelated portproxy entries, and unrelated firewall rules. It stores the
managed mapping in `lan.json` alongside the installation's configuration,
and restricts the Windows Firewall inbound rule to the selected host IP and
client subnet. It does not open a public Internet listener.

On `weave start` and `weave restart`, the WSL NAT destination is refreshed
if forwarding was enabled. The existing interactive-logon WSL session task
also attempts to refresh after it launches Docker. To change the host LAN IP
or subnet, first run `weave lan --remove` and then configure a new mapping.
A failed refresh must be investigated before an exam; verify the endpoint
from a separate student computer, not just localhost.

This is a Windows WSL2 **NAT-mode** helper, not a general solution for
mirrored networking, VPNs, multiple-subnet school networks, or public exposure.
The WSL keeper remains an interactive-logon task and cannot serve schools
before sign-in or after sign-out. A reboot and sign-in acceptance test is
required before claiming reliable overnight hosting.

### Troubleshooting: `weave network recommend` cannot select a school adapter

If the CLI reports `Cannot safely select one adapter`, start with the
read-only commands below in **Windows PowerShell**:

```powershell
weave network interfaces
Get-NetConnectionProfile
```

An active physical Wi-Fi/Ethernet adapter can have a private IPv4 address
(e.g. `172.21.222.123`) yet still have a **Public** Windows network
profile. WEAVE intentionally excludes Public profiles and virtual VMware/WSL
adapters from automatic recommendations. It accepts only one unambiguous,
active, trusted private school subnet (/24 or narrower); it does not guess
between multiple candidates.

**Only on a network you own and trust** (such as a dedicated school LAN),
run PowerShell **as Administrator** and set the relevant physical adapter
to Private. Replace `Wi-Fi` with the exact interface alias reported on your
machine; do not use this on public/shared Wi-Fi or an untrusted hotspot:

```powershell
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private
Get-NetConnectionProfile -InterfaceAlias "Wi-Fi"
weave network recommend
```

If exactly one safe adapter is recommended, configure forwarding only after
reviewing the listener address and allowed client subnet:

```powershell
weave network configure --auto
weave network doctor
weave network url
```

The configure command requires Administrator privileges and explicit
confirmation; it changes WEAVE-owned Windows portproxy and restricted firewall
rules. `network recommend` and `network interfaces` do not modify the
network. Confirm reachability from a **separate student device** on the
authorized subnet. If no adapter is safely recommended, inspect the
physical connection and subnet instead of forcing a public network into
Private or selecting VMware/WSL addresses. For deliberate manual Windows WSL2
NAT mappings, use `weave lan --listen-address <HOST_IP> --client-subnet
<SCHOOL_CIDR>` with verified values.

**Native Linux does not have Windows network profile categories.** The
Private/Domain rule and `weave network configure --auto` are Windows WSL2
specific. On an Ubuntu/Debian CBT host, run:

```bash
weave network info
weave network doctor
sudo ufw status verbose
```

Check the selected host interface, Docker's published TCP ports, and whether
the host firewall, router/VLAN and (for cloud servers) cloud security-group
rules permit traffic **only from the trusted school subnet**. Never disable
the firewall to diagnose reachability, and do not change UFW rules without
preserving SSH access. A reachable localhost URL does not guarantee students
can connect.

## Database initialization

The compiled one-shot `bootstrap` command exclusively applies `alembic upgrade head`
on a transactional SQLAlchemy connection, serialized by a PostgreSQL
advisory lock. API startup checks the migration revision and schema read-only. Alembic owns both schema creation and revision tracking.
Unversioned, unknown-revision and incompatible databases are rejected instead
of being automatically stamped or repaired.

Revision `20261006_initial_schema` delegates to the frozen SQLAlchemy DDL
snapshot in `backend/app/core/schema_baseline.py`. It includes the consolidated
result void auditing and assessment date columns. Do not regenerate this
snapshot from changing models: add subsequent Alembic revisions instead.
Model imports are used for schema validation and autogeneration, never to
independently create or stamp tables at runtime. Initial schema downgrade is
intentionally refused because it would erase school data.

Databases marked with the removed `20261007_*` revisions require explicit
schema verification and adoption to the consolidated baseline before running
this image. Do not blindly stamp a database whose schema is incomplete.

## Local image and schema rollback

The installed `weave update` command selects the manager's bundled,
release-pinned Docker digest by default. Advanced operators can explicitly use
`weave update --image <pinned-image>`; default channel/API mismatches are
rejected before changing containers. Updates require interactive confirmation
and take a **database snapshot before running new migrations**:

1. Pull the new image while the old containers still serve requests.
2. Quiesce Nginx, all three API replicas, and the worker (stop writers).
3. Clone the local PostgreSQL database via `CREATE DATABASE ... TEMPLATE ...`.
   Allow enough local disk space for a second full database.
4. Start the updated Compose stack. The one-shot bootstrap service applies
   Alembic migrations; API/worker wait for successful completion.
5. Verify bootstrap exit code and application readiness. Retain the original
   image/database restore point until the next successful update begins.

If the new image fails, the CLI automatically stops the containers, swaps the
saved PostgreSQL snapshot into the original database name, restores the old
image, and verifies startup. No automatic Alembic downgrade is attempted.
The upgraded database is retained temporarily for troubleshooting until
successful restoration/cleanup. If rollback itself fails, the recovery journal
is preserved and normal `weave start` / `weave restart` are blocked.
After resolving the issue, run `weave rollback`.

You may also run `weave rollback` after a successful update to restore the
previous image and schema. **This restores all school data to the point of the
pre-update snapshot. Attempts, exam answers, results and other records written
since the update will be lost.** Use it only with explicit authorization, with
exams stopped. Avoid upgrading during an active examination. The rollback
journal is stored in the installation data directory without credentials.
The previous rollback snapshot is discarded before a subsequent update.

Docker Compose's `bootstrap` service handles migration ordering even if an
operator uses `docker compose up -d` directly. Merely pulling an image does
not run migrations or replace running containers.

The Python package is `weave_cli`; `cli/src` is its source directory and is
not part of an import path. Use imports such as:

```python
from weave_cli.platforms.base import BasePlatform
from weave_cli.docker.runtime import DockerRuntime
from weave_cli.docker.compose import DockerCompose
```

From the repository root, install the deployment project and run its tests:

```powershell
uv sync --project deployment
uv run --project deployment python -m unittest discover -s deployment/cli/tests -v
```

Run a package module with `uv run --project deployment python -m weave_cli.<module>`.
When working inside `deployment`, omit `--project deployment`. Running
`weave_cli.docker.compose` currently follows the configured API container logs.

Build the installable distributions with `uv build deployment`.
Use the deployment Python environment (`deployment/.venv`) in your editor
when working on this package so it can resolve these installed imports.

On Windows, `install`, `start`, and `restart` ensure a hidden scheduled task
named `WEAVE CBT Runtime - WeaveCBT` holds a WSL session open. Docker's systemd
service alone does not keep WSL alive. The task starts immediately and at the
installation owner's Windows sign-in, and retries when the WSL process exits.
Run `uv run weave start` from Administrator PowerShell once to configure this
for an existing installation. You can then close the WSL terminal.

The task runs under the Windows user who owns the WSL distribution, not SYSTEM.
It requires that user to be signed in; it does not provide service availability
before sign-in or after sign-out. `uninstall` removes the task, while `stop`
stops application containers and leaves runtime management in place. Native
Linux continues to use its existing systemd Docker service.


## Unified school network management (staging)

The supported technician commands live beneath `weave network`:

- `weave network status --json` inspects adapters and recorded school settings.
- `weave network trust --interface "Wi-Fi"` asks the administrator to approve an owned school network before changing its Windows profile from Public to Private.
- `weave network setup --auto` configures one unambiguous approved school adapter. Use `--listen-address IP --client-subnet CIDR` for an explicitly selected adapter.
- `weave network refresh` restores the saved Windows-to-WSL forwarding after WSL restarts; `weave network remove` removes only WEAVE-owned forwarding.
- `weave network url` shows the paired HTTPS hostname after TLS activation, otherwise it warns and displays the HTTP LAN URL. The Desktop Manager copies the same CLI result.
- `weave network dns setup` optionally downloads a SHA-256-pinned CoreDNS executable and registers a headless Windows service **after pairing and HTTPS activation**. It does not alter router settings or install another DHCP server. `weave network dns status` reports local configuration and `weave network dns remove` removes the WEAVE-owned service.

The old `weave lan` command remains as a hidden compatibility entry point. Existing saved LAN state (`lan.json`, `tls-lan.json`) is retained. The runtime keeper now calls `weave network refresh`.

**Router configuration remains manual:** reserve the CBT host LAN IP; after a local DNS test from another school device, configure the router's DHCP DNS server to point to that IP. DNS is not proven school-wide by a successful server-local check. Never enable the router's DNS pointing at the CBT server before UDP and TCP 53 reachability and ordinary DNS forwarding are verified. A DNS service outage can affect all DHCP clients using it. CoreDNS is optional on both Windows WSL2 and native Linux installations: Windows uses a dedicated native Windows service, and Linux uses the managed `weave-cbt-coredns.service` systemd service. On Linux, `sudo weave network dns setup` selects the only unambiguous private /24-or-narrower network; add `--interface eth0` to select an explicit school interface. Installation downloads the official CoreDNS Linux amd64 release and verifies its pinned SHA-256 before installing any unit. Configure Linux host firewall ingress for **UDP and TCP port 53 from the school subnet only**, and verify from another school client before editing router DHCP DNS. Uninstall and `weave network dns remove` remove the WEAVE-owned systemd unit; restore router DNS first. Restoring the router's previous DNS setting is required before removing the local DNS service.

Never trust unknown hotspots, overwrite a non-WEAVE DNS service or change another application's firewall rules. All network changes require explicit administrator approval. The paired HTTPS certificate and examination volumes are unaffected by DNS setup.
