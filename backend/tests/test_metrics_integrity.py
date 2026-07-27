"""Measurement integrity: the numbers this tool reports must describe the model.

Every test here guards a defect that silently corrupted a benchmark result
rather than failing loudly, which is the dangerous kind for a measurement tool.
"""
from __future__ import annotations

import httpx
import pytest

from app.graders.scoring import performance_index
from app.jobs.engine import _server_generation_rate, _server_prompt_rate
from app.services.openai_client import chat_completion

SSE_OK = (
    'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


def _sse_response() -> httpx.Response:
    return httpx.Response(200, text=SSE_OK, headers={"Content-Type": "text/event-stream"})


@pytest.mark.asyncio
async def test_latency_excludes_retry_backoff():
    """TTFT must time the successful attempt, not the failures before it.

    Regression: `start` was taken once before the retry loop, so backoff sleeps
    and dead attempts were folded into TTFT -- a transient 503 made the model
    look seconds slower than it was.
    """
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return _sse_response()

    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, max_retries=3, backoff_base=0.25, backoff_max=1.0,
        transport=httpx.MockTransport(handler),
    )
    assert calls["n"] == 3
    assert result.retry_count == 2
    assert result.content == "hello"
    # ~0.75s of backoff elapsed; none of it belongs to the model's latency.
    assert result.time_to_first_token < 0.25
    assert result.total_response_time < 0.25
    # ...but it is still available for diagnostics.
    assert result.wall_time >= 0.7


@pytest.mark.asyncio
async def test_streaming_requests_usage_so_tokens_are_not_estimated():
    """Without stream_options every streamed run reports guessed token counts."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        seen.update(_json.loads(request.content))
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7,'
                '"total_tokens":18}}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, transport=httpx.MockTransport(handler),
    )
    assert seen.get("stream_options") == {"include_usage": True}
    assert result.usage["completion_tokens"] == 7
    assert result.usage["prompt_tokens"] == 11


@pytest.mark.asyncio
async def test_server_rejecting_stream_options_still_completes():
    """A server that refuses stream_options must lose token counts, not the run."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        body = _json.loads(request.content)
        calls["n"] += 1
        if "stream_options" in body:
            return httpx.Response(
                400,
                json={"error": {"message": "unrecognized argument: stream_options"}},
            )
        return _sse_response()

    # max_retries=0 proves the fallback does not consume the retry budget.
    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert result.error is None
    assert result.content == "hello"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_server_rejecting_with_a_generic_message_still_completes():
    """Many servers reject unknown fields without naming them.

    Matching only on the literal string "stream_options" would turn every
    prompt against such a server into a hard failure.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        if "stream_options" in _json.loads(request.content):
            return httpx.Response(
                422, json={"error": {"message": "extra inputs are not permitted"}}
            )
        return _sse_response()

    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert result.error is None
    assert result.content == "hello"


@pytest.mark.asyncio
async def test_genuine_bad_request_still_fails_and_does_not_loop():
    """The fallback must fire at most once, then surface the real error."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"message": "model not found"}})

    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="nope",
        messages=[{"role": "user", "content": "x"}],
        stream=True, max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert result.error is not None
    assert "model not found" in result.error
    # One try with the field, one without -- never an unbounded loop.
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_auth_failure_is_not_mistaken_for_a_stream_options_problem():
    """A 401 is about credentials; retrying without the field just wastes a call."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    result = await chat_completion(
        "http://test.local/v1", api_key="bad", model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, max_retries=0, transport=httpx.MockTransport(handler),
    )
    assert result.error is not None
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_server_reported_timings_are_captured():
    """llama.cpp reports the true generation rate; dividing tokens by wall time
    understates it by ~25% because prefill and network are folded in."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens":24,"completion_tokens":150,'
                '"total_tokens":174},"timings":{"predicted_per_second":92.4,'
                '"prompt_per_second":67.5,"prompt_ms":356.0}}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    result = await chat_completion(
        "http://test.local/v1", api_key=None, model="m",
        messages=[{"role": "user", "content": "x"}],
        stream=True, transport=httpx.MockTransport(handler),
    )
    assert result.server_timings["predicted_per_second"] == 92.4
    assert _server_generation_rate(result.server_timings) == 92.4
    assert _server_prompt_rate(result.server_timings) == 67.5


def test_generation_rate_helpers_reject_junk():
    """A server sending nulls or zeros must fall back to client-side timing."""
    for bad in (None, {}, {"predicted_per_second": None}, {"predicted_per_second": 0},
                {"predicted_per_second": -1}, {"predicted_per_second": "fast"},
                {"predicted_per_second": True}):
        assert _server_generation_rate(bad) is None


THRESHOLDS = {"desired_ttft": 0.6, "max_ttft": 12.0, "desired_tps": 80.0,
              "min_tps": 4.0, "max_failure_rate": 0.1}


def test_unmeasurable_component_does_not_zero_the_performance_index():
    """A non-streaming run cannot report TTFT; that is not a performance fault.

    Regression: the missing component scored 0 and kept its 30% weight, capping
    a flawless non-streaming run at 70.
    """
    fast = [{"time_to_first_token": 0.1, "output_tokens_per_second": 200.0, "failed": False}] * 5
    no_ttft = [{"time_to_first_token": None, "output_tokens_per_second": 200.0, "failed": False}] * 5
    assert performance_index(metrics=fast, thresholds=THRESHOLDS) == 100.0
    assert performance_index(metrics=no_ttft, thresholds=THRESHOLDS) == 100.0


def test_performance_index_still_punishes_real_slowness():
    """Redistributing weight must not make the index unable to discriminate.

    A slow-but-reliable run keeps the full failure component (nothing failed),
    so the floor here is ~33, not 0 -- what matters is the wide separation from
    a fast run and that speed still dominates the remaining 70%.
    """
    fast = [{"time_to_first_token": 0.1, "output_tokens_per_second": 200.0, "failed": False}] * 5
    slow = [{"time_to_first_token": 11.0, "output_tokens_per_second": 5.0, "failed": False}] * 5
    fast_score = performance_index(metrics=fast, thresholds=THRESHOLDS)
    slow_score = performance_index(metrics=slow, thresholds=THRESHOLDS)
    assert fast_score == 100.0
    assert slow_score < 40.0
    assert fast_score - slow_score > 60.0


def test_performance_index_penalizes_failures():
    half_failed = [
        {"time_to_first_token": 0.1, "output_tokens_per_second": 200.0, "failed": i % 2 == 0}
        for i in range(6)
    ]
    # Speed is perfect, so only the 30% failure component should be lost.
    assert performance_index(metrics=half_failed, thresholds=THRESHOLDS) == pytest.approx(70.0)
