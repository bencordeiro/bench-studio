"""Tests for the OpenAI-compatible client: streaming parse, retries, errors."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from app.services.openai_client import (
    OpenAIClientError,
    RETRYABLE_STATUS,
    chat_completion,
    _extract_stream_chunk,
    _delta_text,
)


def test_extract_stream_chunk_data_done():
    assert _extract_stream_chunk("data: [DONE]") == {"__done__": True}


def test_extract_stream_chunk_json():
    chunk = _extract_stream_chunk('data: {"choices": [{"delta": {"content": "hi"}}]}')
    assert chunk["choices"][0]["delta"]["content"] == "hi"


def test_extract_stream_chunk_ignores_comment_lines():
    assert _extract_stream_chunk(": keepalive") is None
    assert _extract_stream_chunk("") is None


def test_extract_stream_chunk_malformed_returns_none():
    assert _extract_stream_chunk("data: not json") is None


def test_delta_text_and_finish():
    text, finish = _delta_text({"choices": [{"delta": {"content": " world"}, "finish_reason": None}]})
    assert text == " world"
    assert finish is None


def test_delta_text_finish_reason():
    _, finish = _delta_text({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    assert finish == "stop"


def test_delta_text_empty_choices():
    text, finish = _delta_text({})
    assert text == ""
    assert finish is None


@pytest.mark.asyncio
async def test_streaming_parse_and_ttft():
    lines = [
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}',
        "data: [DONE]",
    ]
    body = "\n".join(lines)
    with respx.mock(base_url="http://test") as mock:
        mock.post("/v1/chat/completions").respond(
            200, text=body, headers={"content-type": "text/event-stream"}
        )
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=True, max_retries=0,
        )
    assert result.content == "Hello world"
    assert result.finish_reason == "stop"
    assert result.http_status == 200
    assert result.time_to_first_token is not None
    assert result.usage["total_tokens"] == 7


@pytest.mark.asyncio
async def test_nonstreaming_parse():
    payload = {
        "choices": [{"message": {"content": "hi there"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    with respx.mock(base_url="http://test") as mock:
        mock.post("/v1/chat/completions").respond(200, json=payload)
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=0,
        )
    assert result.content == "hi there"
    assert result.finish_reason == "stop"
    assert result.time_to_first_token is None  # unavailable non-streaming
    assert result.usage["total_tokens"] == 3


@pytest.mark.asyncio
async def test_retry_on_503_then_success():
    payload = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    with respx.mock(base_url="http://test") as mock:
        route = mock.post("/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(503, text="service unavailable"),
                httpx.Response(200, json=payload),
            ]
        )
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=3, backoff_base=0.01, backoff_max=0.05,
        )
    assert result.content == "ok"
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_no_retry_on_400_permanent_error():
    with respx.mock(base_url="http://test") as mock:
        route = mock.post("/v1/chat/completions").respond(400, json={"error": {"message": "bad model"}})
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=3,
        )
    assert result.error is not None
    assert "400" in result.error
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_retries_exhausted_returns_error():
    with respx.mock(base_url="http://test") as mock:
        mock.post("/v1/chat/completions").respond(503, text="down")
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=2, backoff_base=0.01, backoff_max=0.02,
        )
    assert result.error is not None
    assert result.content == ""
    assert "503" in result.error


@pytest.mark.asyncio
async def test_connection_error_is_retryable():
    with respx.mock(base_url="http://test") as mock:
        mock.post("/v1/chat/completions").mock(side_effect=httpx.ConnectError("no connection"))
        result = await chat_completion(
            "http://test", api_key=None, model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=1, backoff_base=0.01, backoff_max=0.02,
        )
    assert result.error is not None
    assert "no connection" in result.error or "ConnectError" in result.error


@pytest.mark.asyncio
async def test_api_key_not_in_error_message():
    # If a key were leaked into an error, it would be redacted.
    with respx.mock(base_url="http://test") as mock:
        mock.post("/v1/chat/completions").respond(401, json={"error": {"message": "invalid key sk-LEAKED1234567890abcd"}})
        result = await chat_completion(
            "http://test", api_key="sk-LEAKED1234567890abcd", model="m",
            messages=[{"role": "user", "content": "hi"}],
            stream=False, max_retries=0,
        )
    assert result.error is not None
    assert "sk-LEAKED1234567890abcd" not in result.error


def test_retryable_status_set():
    assert 429 in RETRYABLE_STATUS
    assert 502 in RETRYABLE_STATUS
    assert 503 in RETRYABLE_STATUS
    assert 504 in RETRYABLE_STATUS
    assert 400 not in RETRYABLE_STATUS
    assert 404 not in RETRYABLE_STATUS
