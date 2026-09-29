"""Tests for the OpenAI-compatible client: streaming parse, retries, errors."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from app.services.openai_client import (
    RETRYABLE_STATUS,
    _build_body,
    _delta_text,
    _extract_stream_chunk,
    chat_completion,
)


def test_build_body_omits_zero_max_tokens():
    """max_tokens=0 means 'server default' — it must not be sent to the model."""
    body = _build_body(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=0.0,
        top_p=None,
        max_tokens=0,
        stop=None,
        seed=None,
        stream=False,
        extra_body={},
    )
    assert "max_tokens" not in body


def test_build_body_sends_positive_max_tokens():
    body = _build_body(
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        temperature=None,
        top_p=None,
        max_tokens=4096,
        stop=None,
        seed=None,
        stream=False,
        extra_body={},
    )
    assert body["max_tokens"] == 4096


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
    content, reasoning, finish = _delta_text({"choices": [{"delta": {"content": " world"}, "finish_reason": None}]})
    assert content == " world"
    assert reasoning == ""
    assert finish is None


def test_delta_text_finish_reason():
    _, _, finish = _delta_text({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    assert finish == "stop"


def test_delta_text_empty_choices():
    content, reasoning, finish = _delta_text({})
    assert content == ""
    assert reasoning == ""
    assert finish is None


def test_delta_text_reasoning_content():
    content, reasoning, finish = _delta_text(
        {"choices": [{"delta": {"reasoning_content": " think think"}, "finish_reason": None}]}
    )
    assert content == ""
    assert reasoning == " think think"
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
async def test_streaming_keeps_reasoning_separate_when_final_answer_missing():
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "The ocean spans vast"}}]}',
        'data: {"choices": [{"delta": {"reasoning_content": " distances and depths."}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13}}',
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
    assert result.content == ""
    assert result.reasoning == "The ocean spans vast distances and depths."
    assert "No final answer" in result.error
    assert result.finish_reason == "stop"
    assert result.raw["fell_back_to_reasoning"] is False


@pytest.mark.asyncio
async def test_streaming_prefers_content_over_reasoning():
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "hidden thought"}}]}',
        'data: {"choices": [{"delta": {"content": "visible answer"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
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
    assert result.content == "visible answer"
    assert result.raw["fell_back_to_reasoning"] is False


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
        mock.post("/v1/chat/completions").mock(
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
        mock.post("/v1/chat/completions").respond(400, json={"error": {"message": "bad model"}})
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


@pytest.mark.parametrize("kind", ["content", "reasoning_content", "keepalive"])
async def test_active_stream_can_exceed_inactivity_timeout(kind):
    class ActiveStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(12):
                await asyncio.sleep(0.01)
                if kind == "keepalive":
                    yield b": keepalive\n\n"
                else:
                    chunk = {"choices": [{"delta": {kind: "answer"}}]}
                    yield f"data: {json.dumps(chunk)}\n\n".encode()
            yield b'data: {"choices":[{"delta":{"content":"final answer"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    def handler(request):
        assert request.extensions["timeout"]["read"] == 0.05
        return httpx.Response(200, stream=ActiveStream())

    result = await asyncio.wait_for(chat_completion(
        "http://test/v1", api_key=None, model="test", messages=[],
        timeout=0.05, max_retries=0, transport=httpx.MockTransport(handler),
    ), timeout=2)
    assert result.error is None
    assert result.wall_time > 0.05


async def test_inactivity_timeout_returns_failure():
    def handler(request):
        raise httpx.ReadTimeout("No incoming data", request=request)

    result = await chat_completion(
        "http://test/v1", api_key=None, model="test", messages=[],
        timeout=0.05, max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert "No incoming data" in result.error


async def test_partial_stream_failure_preserves_reasoning_and_does_not_restart():
    calls = []
    updates = []

    class PartialStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"reasoning_content":"retained thought"}}]}\n\n'
            raise httpx.ReadError("connection lost")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=PartialStream())

    async def progress(fields):
        updates.append(fields)

    result = await chat_completion(
        "http://test/v1", api_key=None, model="test", messages=[],
        transport=httpx.MockTransport(handler), on_progress=progress,
    )
    assert result.reasoning == "retained thought"
    assert result.content == ""
    assert "connection lost" in result.error
    assert len(calls) == 1
    assert updates[0]["reasoning_chars"] == len("retained thought")


async def test_nonstream_reasoning_is_not_graded_as_a_final_answer():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"reasoning_content": "thinking only"}, "finish_reason": "length"}],
        })

    result = await chat_completion(
        "http://test/v1", api_key=None, model="test", messages=[],
        stream=False, transport=httpx.MockTransport(handler),
    )
    assert result.reasoning == "thinking only"
    assert not result.content
    assert "No final answer" in result.error
    assert result.raw["generation_diagnostics"]["truncated"]


def test_repetition_warning_is_observational():
    from app.services.generation_diagnostics import generation_diagnostics

    repeated = "if (type->tp_dict == NULL) ...\n" * 30
    diagnostic = generation_diagnostics("", repeated, "unknown")
    assert diagnostic["possible_repetition"]
    assert diagnostic["no_final_answer"]
    assert not generation_diagnostics("ANSWER: 42", "brief reasoning", "stop")["possible_repetition"]


async def test_empty_network_error_still_marks_request_failed():
    def handler(request):
        raise httpx.ReadTimeout("", request=request)

    result = await chat_completion(
        "http://test/v1", api_key=None, model="test", messages=[], max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    assert result.error
    assert "ReadTimeout" in result.error
