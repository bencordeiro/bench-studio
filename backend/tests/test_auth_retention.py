from __future__ import annotations

from unittest.mock import Mock

import pytest
import respx
from fastapi.testclient import TestClient

from app.core import secrets
from app.jobs.engine import _resolve_key
from app.models import EndpointProfile
from app.services.connection import fetch_models
from app.services.connection import test_connection as check_connection
from app.services.openai_client import _build_headers


@pytest.fixture(autouse=True)
def clear_session_keys():
    secrets._session_keys.clear()
    yield
    secrets._session_keys.clear()


def test_no_keyring_retains_key_for_test_models_and_runner(monkeypatch):
    monkeypatch.setattr(secrets, "_import_keyring", lambda: None)
    assert secrets.store_api_key("profile", "valid-test-key") == "session"
    assert secrets.resolve_api_key("profile", stored_value=True, env_var=None, session_key=None) == ("valid-test-key", "session")
    profile = EndpointProfile(id="profile", has_api_key=True, api_key_env_var="")
    assert _resolve_key(profile, None) == "valid-test-key"
    secrets.delete_api_key("profile")
    assert secrets.get_api_key("profile") is None
    with pytest.raises(ValueError, match="API key is unavailable"):
        _resolve_key(profile, None)


def test_failed_keyring_write_retains_session_key(monkeypatch):
    keyring = Mock()
    keyring.set_password.side_effect = RuntimeError("keyring locked")
    monkeypatch.setattr(secrets, "_import_keyring", lambda: keyring)
    assert secrets.store_api_key("p", "valid-key") == "session"
    assert secrets.get_api_key("p") == "valid-key"


@pytest.mark.parametrize("host", ["api.xiaomimimo.com", "token-plan-sgp.xiaomimimo.com", "token-plan-cn.xiaomimimo.com", "token-plan-ams.xiaomimimo.com"])
def test_mimo_uses_documented_api_key_header(host):
    headers = _build_headers("valid-key", {}, base_url=f"https://{host}/v1")
    assert headers["api-key"] == "valid-key"
    assert "Authorization" not in headers


def test_other_providers_keep_bearer_and_custom_overrides():
    headers = _build_headers("valid-key", {}, base_url="https://api.openai.com/v1")
    assert headers["Authorization"] == "Bearer valid-key"
    assert "api-key" not in headers
    headers = _build_headers("valid-key", {"API-Key": "custom-key"}, base_url="https://api.xiaomimimo.com/v1")
    assert headers["api-key"] == "custom-key"
    assert "API-Key" not in headers


@pytest.mark.parametrize("key", ["tp-fake123456789", "ttp-fake123456789"])
def test_mimo_keys_are_redacted_from_error_text(key):
    from app.core.security import sanitize

    assert key not in sanitize(f"Invalid key {key}")


async def test_lost_session_key_is_reported_without_unauthenticated_requests(monkeypatch):
    monkeypatch.setattr(secrets, "_import_keyring", lambda: None)
    profile = EndpointProfile(id="p", base_url="http://test/v1", has_api_key=True, api_key_env_var="")
    with respx.mock(assert_all_called=False) as mock:
        models = await fetch_models(profile)
        connection = await check_connection(profile)
        assert mock.calls.call_count == 0
    assert "API key is unavailable" in models.error
    assert "API key is unavailable" in connection.error


def test_mimo_key_saved_without_keyring_reaches_models_and_completion(temp_data_dir, monkeypatch):
    from app.main import app

    monkeypatch.setattr(secrets, "_import_keyring", lambda: None)
    with respx.mock() as mock:
        models = mock.get("https://token-plan-sgp.xiaomimimo.com/v1/models").respond(200, json={"data": [{"id": "demo"}]})
        completion = mock.post("https://token-plan-sgp.xiaomimimo.com/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )
        with TestClient(app) as client:
            response = client.post("/api/endpoints", json={
                "name": "MiMo", "base_url": "https://token-plan-sgp.xiaomimimo.com/v1", "default_model": "demo", "api_key": "valid-test-key",
            })
            assert response.status_code == 201
            profile_id = response.json()["id"]
            assert response.json()["api_key_storage"] == "session"
            assert "valid-test-key" not in response.text
            assert client.post(f"/api/endpoints/{profile_id}/models").json()["success"]
            assert client.post(f"/api/endpoints/{profile_id}/test").json()["completion_ok"]
            for route in (models, completion):
                for call in route.calls:
                    assert call.request.headers["api-key"] == "valid-test-key"
                    assert "authorization" not in call.request.headers
            assert "valid-test-key" not in client.get("/api/endpoints").text
