"""Alembic environment configured to use the app's runtime settings and models."""
from __future__ import annotations

import logging
import sys
from logging.config import fileConfig
from pathlib import Path

# Ensure the backend package is importable when alembic runs from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import context  # noqa: E402
from sqlalchemy import engine_from_config, pool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config

# NOTE: We intentionally do NOT call fileConfig() here. The application already
# configures structured logging with secret sanitization; invoking Alembic's
# fileConfig would replace the root logger handlers and discard the sanitizing
# filter. Alembic still logs through the existing handlers.

# Use the runtime DB URL from settings (honors LOCALBENCH_DATA_DIR).
config.set_main_option("sqlalchemy.url", get_settings().db_url)

target_metadata = Base.metadata
log = logging.getLogger("alembic")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-friendly ALTER
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
