"""API integration tests using FastAPI TestClient (no real LLM)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def test_health(temp_data_dir):
    with _client() as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "db_path" in body


def test_endpoint_crud_no_api_key(temp_data_dir):
    with _client() as c:
        r = c.post("/api/endpoints", json={"name": "Local", "base_url": "http://127.0.0.1:11434/v1"})
        assert r.status_code == 201
        eid = r.json()["id"]
        assert r.json()["has_api_key"] is False
        # Get
        assert c.get(f"/api/endpoints/{eid}").status_code == 200
        # List
        lst = c.get("/api/endpoints").json()
        assert len(lst) == 1
        # Update
        upd = c.put(f"/api/endpoints/{eid}", json={"name": "Local", "base_url": "http://127.0.0.1:11434/v1", "default_model": "llama"})
        assert upd.json()["default_model"] == "llama"
        # Duplicate
        dup = c.post(f"/api/endpoints/{eid}/duplicate")
        assert dup.status_code == 200
        assert c.get("/api/endpoints").json().__len__() == 2
        # Delete
        c.delete(f"/api/endpoints/{eid}")
        assert c.get(f"/api/endpoints/{eid}").status_code == 404


def test_api_key_never_returned(temp_data_dir):
    with _client() as c:
        r = c.post("/api/endpoints", json={"name": "WithKey", "base_url": "http://x/v1", "api_key": "sk-supersecret123"})
        body = r.json()
        assert body["has_api_key"] in (True, False)  # depends on keyring availability
        # Key value must never appear anywhere in the response.
        assert "sk-supersecret123" not in json.dumps(body)
        # And not in the list endpoint.
        assert "sk-supersecret123" not in c.get("/api/endpoints").text


def test_benchmark_crud_and_prompt(temp_data_dir):
    with _client() as c:
        r = c.post("/api/benchmarks", json={"name": "B1", "prompts": [
            {"stable_id": "p1", "title": "P1", "grading_mode": "deterministic",
             "grader_config": {"type": "exact", "canonical_answer": "yes"},
             "messages": [{"role": "user", "content": "say yes"}]},
        ]})
        bid = r.json()["id"]
        detail = c.get(f"/api/benchmarks/{bid}").json()
        assert len(detail["prompts"]) == 1
        # Add a prompt
        c.post(f"/api/benchmarks/{bid}/prompts", json={
            "stable_id": "p2", "title": "P2", "grading_mode": "manual",
            "grader_config": {}, "messages": [{"role": "user", "content": "be creative"}],
        })
        detail = c.get(f"/api/benchmarks/{bid}").json()
        assert len(detail["prompts"]) == 2
        # Reorder
        ids = [p["id"] for p in reversed(detail["prompts"])]
        c.post(f"/api/benchmarks/{bid}/reorder", json={"prompt_ids": ids})
        # Duplicate prompt
        c.post(f"/api/benchmarks/{bid}/prompts/{detail['prompts'][0]['id']}/duplicate")
        assert len(c.get(f"/api/benchmarks/{bid}").json()["prompts"]) == 3


def test_benchmark_export_import_roundtrip(temp_data_dir):
    with _client() as c:
        c.post("/api/benchmarks", json={"name": "Export", "prompts": [
            {"stable_id": "x", "title": "X", "grading_mode": "deterministic",
             "grader_config": {"type": "exact", "canonical_answer": "42"},
             "messages": [{"role": "user", "content": "answer"}]},
        ]})
        bid = c.get("/api/benchmarks").json()[0]["id"]
        # Export
        export = c.get(f"/api/benchmarks/{bid}/export")
        document = export.json()
        assert document["format"] == "localbench-benchmark"
        # Import as new
        import_res = c.post("/api/benchmarks/import", files={"file": ("b.json", json.dumps(document).encode(), "application/json")})
        assert import_res.status_code == 200
        assert len(c.get("/api/benchmarks").json()) == 2


def test_run_export_contains_no_api_key(temp_data_dir):
    with _client() as c:
        # Create endpoint with a key.
        c.post("/api/endpoints", json={"name": "E", "base_url": "http://x/v1", "api_key": "sk-LEAKME1234567890"})
        c.post("/api/benchmarks", json={"name": "B", "prompts": [
            {"stable_id": "p", "title": "P", "grading_mode": "deterministic",
             "grader_config": {"type": "exact", "canonical_answer": "yes"},
             "messages": [{"role": "user", "content": "q"}]},
        ]})
        bid = c.get("/api/benchmarks").json()[0]["id"]
        eid = c.get("/api/endpoints").json()[0]["id"]
        run = c.post("/api/runs", json={"benchmark_id": bid, "target_endpoint_id": eid, "target_model": "m", "auto_start": False})
        rid = run.json()["id"]
        for fmt in ["json", "csv", "html"]:
            body = c.get(f"/api/runs/{rid}/export/{fmt}").text
            assert "sk-LEAKME1234567890" not in body, f"API key leaked in {fmt} export"


def test_run_creation_validation(temp_data_dir):
    with _client() as c:
        # No benchmark -> 400
        r = c.post("/api/runs", json={"benchmark_id": "missing", "target_endpoint_id": "missing"})
        assert r.status_code == 400


def test_compare_route_not_swallowed(temp_data_dir):
    """GET /api/runs/compare must not be matched by /{run_id}."""
    with _client() as c:
        # With fewer than 2 ids it should 400 (proving the route resolved),
        # NOT 404 ("Run 'compare' not found").
        r = c.get("/api/runs/compare")
        assert r.status_code == 400
        assert "two" in r.json()["detail"].lower()


def test_settings_roundtrip(temp_data_dir):
    with _client() as c:
        s = c.get("/api/settings").json()
        s["log_level"] = "DEBUG"
        updated = c.put("/api/settings", json=s).json()
        assert updated["log_level"] == "DEBUG"


def test_diagnostics(temp_data_dir):
    with _client() as c:
        d = c.get("/api/diagnostics").json()
        assert "application_version" in d
        assert "python_version" in d
