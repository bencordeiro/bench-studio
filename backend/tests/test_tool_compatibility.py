from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.openai_client import ChatResult
from app.services.tool_compatibility import (
    PROBE_TEXT,
    annotate_text_tool_failure,
    classify_probe,
    probe_text_tool_calls,
    requires_text_tool_calls,
)


def result(content="", error=None, raw=None):
    return ChatResult(content=content, error=error, raw=raw or {}, finish_reason="unknown",
                      truncated=False, usage={}, http_status=200, time_to_first_token=None,
                      total_response_time=1, retry_count=0)


@pytest.mark.parametrize("response,status", [
    (result(PROBE_TEXT), "compatible"),
    (result(error='HTTP 400: malformed tool call: {"name":"get_weather"}'), "incompatible"),
    (result(raw={"generation_diagnostics": {"native_tool_calls_received": True}}), "incompatible"),
    (result(error="Endpoint stream ended without a finish_reason or [DONE]"), "inconclusive"),
    (result("I cannot call that tool"), "inconclusive"),
    (result(error="HTTP 401: unauthorized"), "inconclusive"),
    (result(error="No final answer", raw={"generation_diagnostics": {"truncated": True}}), "inconclusive"),
])
def test_probe_distinguishes_transport_from_model_failure(response, status):
    assert classify_probe(response)["status"] == status


def test_aborted_tool_response_is_suspected_not_confirmed():
    response = result(error="connection lost", raw={"generation_diagnostics": {"incomplete_stream": True}})
    prompt = {"grader_config": {"checks": [{"type": "tool_call"}]}}
    annotate_text_tool_failure(response, prompt)
    assert "may have aborted" in response.error
    assert response.raw["generation_diagnostics"]["possible_tool_parser_abort"]
    assert "connection lost" in response.error
    assert requires_text_tool_calls(prompt)
    assert not requires_text_tool_calls({"grader_config": {"type": "exact"}})


def test_normal_reasoning_only_answer_stays_model_failure():
    response = result(error="No final answer", raw={"generation_diagnostics": {"incomplete_stream": False}})
    annotate_text_tool_failure(response, {"grader_config": {"type": "tool_call"}})
    assert response.error == "No final answer"


async def test_probe_uses_bounded_nonstream_request_and_preserves_connection_settings(monkeypatch):
    from types import SimpleNamespace

    from app.services import tool_compatibility

    chat = AsyncMock(return_value=result(PROBE_TEXT))
    monkeypatch.setattr(tool_compatibility, "chat_completion", chat)
    profile = SimpleNamespace(base_url="http://test/v1", custom_headers={"X-Test": "value"}, verify_tls=False)
    report = await probe_text_tool_calls(profile, "m", "secret", {"max_tokens": 64, "timeout": 60},
                                         {"max_tokens": 9999, "chat_template_kwargs": {"reasoning_effort": "xhigh"}})
    assert report["status"] == "compatible"
    kwargs = chat.call_args.kwargs
    assert not kwargs["stream"]
    assert kwargs["max_tokens"] == 64
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] == 30
    assert kwargs["api_key"] == "secret"
    assert kwargs["custom_headers"] == {"X-Test": "value"}
    assert "max_tokens" not in kwargs["extra_body"]
    assert kwargs["extra_body"]["chat_template_kwargs"]["reasoning_effort"] == "xhigh"
