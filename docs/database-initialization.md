# Database initialization

Provision PostgreSQL and configure `DATABASE_URL` before starting the API. The
database itself must exist and the configured role must be able to create tables
and functions in its `public` schema.

API lifespan and ARQ worker startup call the same asynchronous schema bootstrap.
On an empty database it imports the complete model registry, creates all current
tables, constraints and indexes, and installs the exam contributor triggers. A
PostgreSQL transaction advisory lock serializes concurrent workers; schema
creation, trigger installation and stamping the current Alembic revision commit
together or roll back together.

On subsequent starts it validates the existing table and column definitions,
primary keys, required indexes, checks, unique constraints, foreign keys and
contributor triggers. It never drops tables, clears records, or silently repairs
a partially initialized database. A leftover migration marker by itself is a
partial schema and is rejected. Existing databases must be stamped at the current
Alembic head. Startup refuses outdated or unversioned schemas.

From `backend/`, initialize or validate explicitly with:

```powershell
uv run python -m app.core.database_bootstrap
```

The compiled executable exposes `weave-cbt bootstrap`. Docker Compose runs that
command as a one-shot `bootstrap` service before API and worker startup. Manager
health checks require its successful exit.

Automatic creation is for fresh installation. Alembic configuration lives in
`backend/alembic.ini` and revisions in `backend/alembic/versions/`. The initial
revision is frozen PostgreSQL DDL, independent of later model changes.

For subsequent schema changes, from `backend/`:

```powershell
uv run alembic revision --autogenerate -m "describe schema change"
# Review the generated migration, including data backfills and custom triggers.
uv run alembic upgrade head
uv run alembic current
```

Apply reviewed migrations with a backup before starting API and worker processes.
Alembic autogeneration does not detect custom PostgreSQL functions and triggers;
write those operations explicitly. A fresh database can also be initialized with
`uv run alembic upgrade head`.

For an existing unversioned database, verify its full schema against the initial
revision before explicitly running `uv run alembic stamp 20261006_initial_schema`.
Stamping only records a version; it never repairs missing tables or columns.
Databases carrying revisions from a removed historical chain require an explicit
schema reconciliation before adoption. Never delete a school database to make
startup pass.

To run the PostgreSQL integration tests, set
`WEAVE_BOOTSTRAP_TEST_DATABASE_URL` to an explicitly designated local test database
connection whose role can create databases, then run
`uv run pytest tests/test_database_bootstrap.py`. Tests create and drop only their
own uniquely named `weave_bootstrap_test_*` databases.

Before handing off or pushing the repository, run `./scripts/Cleanup.ps1` from the
repository root (`-Preview` lists targets). It removes generated caches and
frontend build output while retaining source, virtual environments, credentials,
local media, and database/runtime data.
