"""Alembic wiring without an alembic.ini: migrations ship inside the package."""

from __future__ import annotations

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

SCRIPT_LOCATION = "lones_vdl.db:migrations"


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.attributes["engine"] = engine
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    command.upgrade(alembic_config(engine), revision)


def make_migration(message: str) -> None:
    """Dev helper: autogenerate a revision by diffing models against a scratch DB at head."""
    from lones_vdl.db.base import create_db_engine

    with tempfile.TemporaryDirectory() as tmp:
        engine = create_db_engine(Path(tmp) / "scratch.db")
        try:
            config = alembic_config(engine)
            command.upgrade(config, "head")
            command.revision(config, message=message, autogenerate=True)
        finally:
            engine.dispose()
