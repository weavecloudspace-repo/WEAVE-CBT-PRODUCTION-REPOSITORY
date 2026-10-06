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
