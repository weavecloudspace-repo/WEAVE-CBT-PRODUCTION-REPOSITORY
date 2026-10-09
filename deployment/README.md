# WEAVE deployment tooling

## V1 release and installation architecture

All branches run backend, frontend, CLI and platform bootstrap tests. Only
`staging` and `master` publish application Docker images and compiled CLI
manager installers. Staging publishes prereleases; master publishes production.

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

The installed `weave update --image <pinned-image>` command takes a
**database snapshot before running new migrations**:

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
