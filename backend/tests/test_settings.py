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


def test_saved_settings_survive_refresh_restart_and_control_new_runs(temp_data_dir):
    from app.core.config import reset_settings_for_tests
    from app.db.session import dispose_engine
    from app.main import app

    expected = {
        "default_max_tokens": 4096,
        "default_timeout": 90,
        "default_temperature": 0.3,
        "default_top_p": 0.85,
        "default_retry_max_attempts": 2,
        "default_retry_backoff_base": 1.0,
        "default_retry_backoff_max": 15.0,
        "log_level": "DEBUG",
        "automatic_backup": False,
        "launch_browser": False,
        "composite_weights": {"quality": 0.8, "reliability": 0.15, "performance": 0.05},
    }
    with TestClient(app) as c:
        settings = c.get("/api/settings").json()
        settings.update(expected)
        saved = c.put("/api/settings", json=settings)
        assert saved.status_code == 200
        refreshed = c.get("/api/settings").json()
        assert {key: refreshed[key] for key in expected} == expected

    # Re-open the database and application without any cached runtime state.
    dispose_engine()
    reset_settings_for_tests()
    with TestClient(app) as c:
        restarted = c.get("/api/settings").json()
        assert {key: restarted[key] for key in expected} == expected
        endpoint = c.post("/api/endpoints", json={
            "name": "Local", "base_url": "http://127.0.0.1:8000/v1", "default_model": "test",
        }).json()
        benchmark = c.post("/api/benchmarks", json={
            "name": "Limits test", "prompts": [{
                "stable_id": "p", "title": "Answer", "grading_mode": "deterministic",
                "grader_config": {"type": "exact", "canonical_answer": "yes"},
                "messages": [{"role": "user", "content": "Say yes."}],
            }],
        }).json()
        request = {
            "benchmark_id": benchmark["id"], "target_endpoint_id": endpoint["id"],
            "auto_start": False, "run_config": {"max_tokens": 1, "timeout": 1},
        }
        first = c.post("/api/runs", json=request)
        assert first.status_code == 201
        assert first.json()["run_config"]["max_tokens"] == 4096
        assert first.json()["run_config"]["timeout"] == 90

        restarted.update(default_max_tokens=2048, default_timeout=120)
        assert c.put("/api/settings", json=restarted).status_code == 200
        second = c.post("/api/runs", json=request)
        assert second.status_code == 201
        assert second.json()["run_config"]["max_tokens"] == 2048
        assert second.json()["run_config"]["timeout"] == 120
        original = c.get(f"/api/runs/{first.json()['id']}").json()
        assert original["run_config"]["max_tokens"] == 4096
        assert original["run_config"]["timeout"] == 90
