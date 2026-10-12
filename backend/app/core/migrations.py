"""Resolve Alembic configuration for source and standalone runtimes."""

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def migration_config() -> Config:
    root = (
        Path(sys.executable).resolve().parent
        if "__compiled__" in globals()
        else Path(__file__).resolve().parents[2]
    )
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    return config


def migration_head() -> str:
    head = ScriptDirectory.from_config(migration_config()).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no migration head; refusing initialization.")
    return head


def include_schema_object(obj, name, type_, reflected, compare_to) -> bool:
    """Keep implicit non-native Enum checks out of standalone constraint diffs.

    Alembic excludes SQLAlchemy's type-bound checks on the model side, but
    PostgreSQL reflects them as ordinary checks. Match only those generated
    constraints; explicit application checks remain part of autogeneration.
    """
    if reflected and type_ == "check_constraint":
        from app.core.database import Base

        table = Base.metadata.tables.get(obj.table.name)
        if table is not None and any(
            constraint.name == name and getattr(constraint, "_type_bound", False)
            for constraint in table.constraints
        ):
            return False
    return True
