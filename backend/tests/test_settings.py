"""Settings endpoint defaults.

Regression: _load_settings once hardcoded default_max_tokens=1024, shadowing the
schema default, so raising the schema had no effect and runs truncated.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_settings_default_max_tokens_matches_schema(temp_data_dir):
    from app.main import app
    from app.schemas.settings import AppSettings

    with TestClient(app) as c:
        r = c.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["default_max_tokens"] == AppSettings().default_max_tokens
    assert body["default_max_tokens"] == 0  # 0 = server default (no cap)
