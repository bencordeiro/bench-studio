"""Pytest fixtures: isolated data dir + fresh DB per test."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def temp_data_dir(monkeypatch, tmp_path):
    """Each test gets its own LOCALBENCH_DATA_DIR and a fresh engine."""
    data_dir = tmp_path / "lbs_data"
    data_dir.mkdir()
    monkeypatch.setenv("LOCALBENCH_DATA_DIR", str(data_dir))
    monkeypatch.setenv("LOCALBENCH_NO_SEED", "1")
    # Reset cached settings/engine for isolation.
    from app.core import config as config_mod
    from app.db import session as session_mod

    config_mod.reset_settings_for_tests()
    session_mod.dispose_engine()
    # Apply migrations to the fresh DB.
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{(data_dir / 'localbench.db').as_posix()}")
    command.upgrade(cfg, "head")
    yield data_dir
    session_mod.dispose_engine()
    config_mod.reset_settings_for_tests()


@pytest.fixture
def session():
    from app.db.session import session_scope

    with session_scope() as s:
        yield s


@pytest.fixture
def benchmark_factory(session):
    """Factory to create a benchmark set with N prompts."""
    from app.services import crud

    def _make(name="Test Bench", prompts=None):
        prompts = prompts or []
        return crud.create_benchmark_set(session, {"name": name, "prompts": prompts})

    return _make
