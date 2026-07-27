"""Connection test now probes a real completion (catches auth the /models call misses)."""
from __future__ import annotations

import pytest
import respx

from app.models import EndpointProfile
from app.services.connection import test_connection as run_connection_test


def _prof(base: str = "http://test/v1", model: str = "m1") -> EndpointProfile:
    return EndpointProfile(
        id="x", name="n", base_url=base, default_model=model, request_timeout=10.0,
        verify_tls=True, custom_headers={}, extra_body_params={},
        has_api_key=False, api_key_storage="none", api_key_env_var="",
    )


@pytest.mark.asyncio
async def test_connection_completion_ok():
    with respx.mock(base_url="http://test") as mock:
        mock.get("/v1/models").respond(200, json={"data": [{"id": "m1"}]})
        mock.post("/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )
        res = await run_connection_test(_prof())
    assert res.reachable and res.models_discovered
    assert res.completion_checked and res.completion_ok
    assert res.completion_model == "m1"
    assert res.error is None


@pytest.mark.asyncio
async def test_connection_completion_401_is_caught():
    """The key regression: /models is open (200) but completions require auth (401)."""
    with respx.mock(base_url="http://test") as mock:
        mock.get("/v1/models").respond(200, json={"data": [{"id": "m1"}]})
        mock.post("/v1/chat/completions").respond(
            401, json={"error": {"message": "Invalid API Key"}}
        )
        res = await run_connection_test(_prof())
    assert res.reachable is True          # models endpoint was reachable
    assert res.completion_checked is True
    assert res.completion_ok is False     # ...but a real generation failed
    assert "401" in (res.error or "")


@pytest.mark.asyncio
async def test_connection_no_model_skips_probe():
    with respx.mock(base_url="http://test") as mock:
        mock.get("/v1/models").respond(200, json={"data": []})
        res = await run_connection_test(_prof(model=""))
    assert res.reachable is True
    assert res.completion_ok is False
    assert "model" in (res.error or "").lower()
