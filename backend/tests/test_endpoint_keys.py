"""Regression tests for endpoint API-key handling.

Bug once shipped: the schema marked `api_key` with Field(exclude=True), which
dropped it from model_dump() — so a key submitted via the API never reached
storage and every endpoint stayed keyless. These tests pin both requirements:
the key must survive to storage, and must never be returned in a response.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas import EndpointProfileResponse, EndpointProfileUpdate


def test_api_key_survives_model_dump_for_storage():
    dumped = EndpointProfileUpdate(
        name="n", base_url="http://x:8000/v1", api_key="secret123"
    ).model_dump(exclude_unset=True)
    assert dumped.get("api_key") == "secret123"


def test_api_key_excluded_from_response():
    resp = EndpointProfileResponse(id="1", name="n", base_url="http://x:8000/v1", has_api_key=True)
    assert "api_key" not in resp.model_dump()
    assert "secret" not in resp.model_dump_json()  # no plaintext leak


def test_create_endpoint_stores_key_and_hides_it(temp_data_dir, monkeypatch):
    calls: dict = {}

    def fake_store(profile_id: str, api_key: str) -> str:
        calls["profile_id"] = profile_id
        calls["key"] = api_key
        return "keyring"

    # Avoid touching the real OS keyring during the test.
    monkeypatch.setattr("app.services.crud.store_api_key", fake_store)

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/endpoints", json={
            "name": "E", "base_url": "http://192.0.2.10:8000/v1", "api_key": "topsecret",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["has_api_key"] is True          # key was recorded
        assert "api_key" not in body                 # never returned
        assert "topsecret" not in r.text             # no plaintext anywhere
        assert calls.get("key") == "topsecret"       # reached storage

        # And updating with a new key also flows through to storage.
        pid = body["id"]
        r2 = c.put(f"/api/endpoints/{pid}", json={
            "name": "E", "base_url": "http://192.0.2.10:8000/v1", "api_key": "rotated",
        })
        assert r2.status_code == 200
        assert calls.get("key") == "rotated"
