"""Exercise first-install safety against disposable PostgreSQL databases.

Set WEAVE_BOOTSTRAP_TEST_DATABASE_URL to a local test database connection. Each
test creates and drops its own uniquely named database; the source is untouched.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
from app.core.database_bootstrap import bootstrap_database, verify_database_schema
from app.domains.auth.models import LocalActorSession, LocalRefreshToken


def test_current_schema_contains_durable_runtime_and_auth_contracts():
    assert {
        "cbt_runtime_states",
        "realtime_outbox_events",
        "student_exam_sessions",
    } <= set(Base.metadata.tables)
    assert {
        "weave_access_token_encrypted",
        "weave_access_token_expires_at",
        "weave_refresh_token_encrypted",
        "weave_refresh_token_expires_at",
        "weave_refresh_operation_id",
        "weave_auth_state",
    } <= set(LocalActorSession.__table__.c.keys())
    assert {"refresh_operation_id", "replacement_token_encrypted"} <= set(
        LocalRefreshToken.__table__.c.keys()
    )


@pytest_asyncio.fixture
async def fresh_database():
    source = os.environ.get("WEAVE_BOOTSTRAP_TEST_DATABASE_URL")
    if not source:
        pytest.skip(
            "WEAVE_BOOTSTRAP_TEST_DATABASE_URL is required for disposable PostgreSQL tests"
        )
    url = make_url(source)
    if (
        url.host not in {"localhost", "127.0.0.1"}
        or not url.database
        or "test" not in url.database
    ):
        pytest.fail(
            "Bootstrap integration tests require an explicitly configured local test database"
        )
    database_name = "weave_bootstrap_test_" + uuid4().hex
    admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
    database = create_async_engine(url.set(database=database_name))
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
            created = True
        yield database
    finally:
        await database.dispose()
        if created:
            assert database_name.startswith("weave_bootstrap_test_")
            async with admin.connect() as connection:
                await connection.execute(
                    text(f'DROP DATABASE "{database_name}" WITH (FORCE)')
                )
        await admin.dispose()


@pytest.mark.asyncio
async def test_api_startup_does_not_migrate_a_fresh_database(fresh_database):
    with pytest.raises(RuntimeError, match="has not been migrated"):
        await verify_database_schema(fresh_database)
    async with fresh_database.connect() as connection:
        assert not list(
            (await connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ))).scalars()
        )


@pytest.mark.asyncio
async def test_api_startup_verifies_migrated_database_read_only(fresh_database):
    assert await bootstrap_database(fresh_database) is True
    await verify_database_schema(fresh_database)
    async with fresh_database.connect() as connection:
        assert (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one() == "20261006_initial_schema"


@pytest.mark.asyncio
async def test_api_startup_rejects_outdated_revision_without_upgrading(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(text(
            "UPDATE alembic_version SET version_num = 'unknown_old_revision'"
        ))
    with pytest.raises(RuntimeError, match="do not match migration head"):
        await verify_database_schema(fresh_database)
    async with fresh_database.connect() as connection:
        assert (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one() == "unknown_old_revision"


@pytest.mark.asyncio
async def test_fresh_startup_and_restart_preserve_data(fresh_database):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.core.migrations import include_schema_object

    assert await bootstrap_database(fresh_database) is True
    async with fresh_database.begin() as connection:
        tables = set(
            (
                await connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        assert tables == set(Base.metadata.tables) | {"alembic_version"}
        assert (
            await connection.run_sync(
                lambda sync: compare_metadata(
                    MigrationContext.configure(
                        sync,
                        opts={
                            "compare_type": True,
                            "compare_server_default": True,
                            "include_object": include_schema_object,
                        },
                    ),
                    Base.metadata,
                )
            )
            == []
        )
        assert (
            await connection.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one() == "20261006_initial_schema"
        await connection.execute(
            text("CREATE TABLE public.bootstrap_sentinel (value text NOT NULL)")
        )
        await connection.execute(
            text("INSERT INTO public.bootstrap_sentinel VALUES ('keep me')")
        )
    assert await bootstrap_database(fresh_database) is False
    async with fresh_database.connect() as connection:
        assert (
            await connection.execute(
                text("SELECT value FROM public.bootstrap_sentinel")
            )
        ).scalar_one() == "keep me"


@pytest.mark.asyncio
async def test_unversioned_schema_is_not_silently_adopted(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(text("DROP TABLE public.alembic_version"))
    with pytest.raises(RuntimeError, match="Refusing automatic repair or stamping"):
        await bootstrap_database(fresh_database)
    async with fresh_database.connect() as connection:
        assert (
            await connection.execute(
                text("SELECT to_regclass('public.alembic_version')")
            )
        ).scalar_one() is None


@pytest.mark.asyncio
async def test_outdated_revision_requires_explicit_upgrade(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(
            text(
                "UPDATE public.alembic_version SET version_num = 'unknown_old_revision'"
            )
        )
    with pytest.raises(RuntimeError, match="requires an Alembic upgrade"):
        await bootstrap_database(fresh_database)


@pytest.mark.asyncio
async def test_concurrent_startup_initializes_exactly_once(fresh_database):
    results = await asyncio.gather(
        *(bootstrap_database(fresh_database) for _ in range(3))
    )
    assert results.count(True) == 1
    assert results.count(False) == 2


@pytest.mark.asyncio
async def test_partial_schema_is_rejected_without_repair(fresh_database):
    async with fresh_database.begin() as connection:
        await connection.execute(
            text("CREATE TABLE public.alembic_version (version_num text)")
        )
    with pytest.raises(RuntimeError, match="Refusing automatic repair"):
        await bootstrap_database(fresh_database)
    async with fresh_database.connect() as connection:
        tables = set(
            (
                await connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )
        assert tables == {"alembic_version"}


@pytest.mark.asyncio
async def test_old_column_definition_is_rejected(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(
            text("ALTER TABLE public.exams ALTER COLUMN status TYPE varchar(8)")
        )
    with pytest.raises(RuntimeError, match="exams.status has an incompatible"):
        await bootstrap_database(fresh_database)


@pytest.mark.asyncio
async def test_missing_contributor_trigger_is_rejected(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(
            text(
                "DROP TRIGGER trg_exam_selection_contributor ON public.exam_question_selections"
            )
        )
    with pytest.raises(
        RuntimeError, match="trigger trg_exam_selection_contributor is missing"
    ):
        await bootstrap_database(fresh_database)


@pytest.mark.asyncio
async def test_failed_initialization_rolls_back_all_tables(fresh_database, monkeypatch):
    from app.core.schema_baseline import create_schema

    def fail(_connection):
        create_schema(_connection)
        raise RuntimeError("baseline installation failed")

    monkeypatch.setattr("app.core.schema_baseline.create_schema", fail)
    with pytest.raises(RuntimeError, match="baseline installation failed"):
        await bootstrap_database(fresh_database)
    async with fresh_database.connect() as connection:
        assert not list(
            (
                await connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_missing_resume_check_is_rejected(fresh_database):
    await bootstrap_database(fresh_database)
    async with fresh_database.begin() as connection:
        await connection.execute(
            text(
                "ALTER TABLE public.attempt_interruptions "
                "DROP CONSTRAINT ck_attempt_interruptions_resume_actor_required"
            )
        )
    with pytest.raises(RuntimeError, match="resume_actor_required is missing"):
        await bootstrap_database(fresh_database)


@pytest.mark.asyncio
@pytest.mark.parametrize("already_initialized", [False, True])
async def test_future_migration_does_not_duplicate_current_model_column(
    fresh_database, monkeypatch, tmp_path, already_initialized
):
    from alembic.config import Config
    from sqlalchemy import Column, String

    from app.core.migrations import migration_config

    if already_initialized:
        await bootstrap_database(fresh_database)
    source = migration_config()
    scripts = tmp_path / "alembic"
    shutil.copytree(source.get_main_option("script_location"), scripts)
    (scripts / "versions" / "future_probe.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        'revision = "future_probe"\n'
        'down_revision = "20261006_initial_schema"\n'
        "def upgrade():\n"
        '    op.add_column("school_profiles", sa.Column("future_probe", sa.String(40)))\n',
        encoding="utf-8",
    )

    def future_config():
        config = Config(source.config_file_name)
        config.set_main_option("script_location", str(scripts))
        return config

    monkeypatch.setattr("app.core.database_bootstrap.migration_config", future_config)
    monkeypatch.setattr(
        "app.core.database_bootstrap.migration_head", lambda: "future_probe"
    )
    table = Base.metadata.tables["school_profiles"]
    probe = Column("future_probe", String(40))
    table.append_column(probe)
    try:
        assert await bootstrap_database(fresh_database) is (not already_initialized)
        assert await bootstrap_database(fresh_database) is False
        async with fresh_database.connect() as connection:
            assert (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one() == "future_probe"
            await connection.execute(text("SELECT future_probe FROM school_profiles"))
    finally:
        table._columns.remove(probe)
