# WEAVE deployment tooling

## Image publishing

The `WEAVE CBT image` workflow runs frontend/backend validation, builds the
current `runtime` Docker target, and verifies Compose bootstrap plus staff,
student and API routes before publishing. Pull requests build and verify only.
Pushes to `implementing-services` publish
`ghcr.io/weavecloudspace-repo/weave-cbt-production-repository:sha-<full-commit>`
and update its `implementing-services` tag. Use the commit tag or image digest
for reproducible installations. Windows setup EXE and Manager release publishing
are no longer part of CI. Existing CLI/bootstrap validation workflows remain.

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
