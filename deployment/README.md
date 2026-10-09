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

The compiled `bootstrap` command and API startup apply `alembic upgrade head`
on the same transactional SQLAlchemy connection, serialized by a PostgreSQL
advisory lock. Alembic owns both schema creation and revision tracking.
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
