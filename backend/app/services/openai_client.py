"""OpenAI-compatible HTTP client with streaming, usage parsing, and retries."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from app.core.security import sanitize
from app.core.urls import chat_completions_url
from app.services.generation_diagnostics import generation_diagnostics

log = logging.getLogger(__name__)

# HTTP statuses considered transient and retryable.
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
# Retryable exception types (network/timeout).
RETRYABLE_EXCEPTIONS = tuple(
    exc for exc in (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.ConnectTimeout,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        getattr(httpx, "ConcurrencyError", None),
    )
    if exc is not None
)


class OpenAIClientError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable

    @property
    def sanitized_message(self) -> str:
        return str(self)


def _sanitize_error_message(message: str) -> str:
    """Remove secret-bearing content from error strings before storage/logging."""
    return sanitize(message) if isinstance(sanitize(message), str) else message


@dataclass
class ChatResult:
    content: str
    finish_reason: str
    truncated: bool
    usage: dict[str, Any]
    http_status: int
    time_to_first_token: float | None
    total_response_time: float
    retry_count: int
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # Wall-clock across every attempt including backoff sleeps. Kept separate
    # from total_response_time so retries never inflate the reported latency.
    wall_time: float | None = None
    # Server-reported timing block, when the backend provides one (llama.cpp
    # sends `timings`). Lets us record the true generation rate instead of
    # diluting it with prefill and network time.
    server_timings: dict[str, Any] | None = None
    reasoning: str = ""


def _build_headers(
    api_key: str | None, custom_headers: dict[str, str] | None
) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for k, v in (custom_headers or {}).items():
        # Lowercase compare to avoid duplicate auth headers leaking the real key in logs.
        if k.lower() == "authorization":
            headers["Authorization"] = v
        elif k.lower() == "content-type":
            headers["Content-Type"] = v
        else:
            headers[k] = v
    return headers


def _build_body(
    messages: list[dict[str, str]],
    model: str,
    *,
    temperature: float | None,
    top_p: float | None,
    max_tokens: int | None,
    stop: list[str] | None,
    seed: int | None,
    stream: bool,
    extra_body: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    if stream:
        # Ask for a final usage chunk. vLLM, llama.cpp, LM Studio, TGI and the
        # OpenAI API all honour this; servers that don't simply ignore it and we
        # fall back to estimating from character count. Without it every
        # streamed run reports estimated tokens, and tokens/sec (40% of the
        # performance index) is derived from a guess.
        body["stream_options"] = {"include_usage": True}
    if temperature is not None:
        body["temperature"] = temperature
    if top_p is not None:
        body["top_p"] = top_p
    if max_tokens is not None and max_tokens > 0:
        body["max_tokens"] = max_tokens
    if stop:
        body["stop"] = stop
    if seed is not None:
        body["seed"] = seed
    # Extra user-defined params (never let them override stream silently).
    for k, v in (extra_body or {}).items():
        if k == "stream":
            continue
        body[k] = v
    return body


def _extract_stream_chunk(line: str) -> dict[str, Any] | None:
    """Parse a single SSE line into a JSON chunk, tolerating malformed input."""
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if payload == "[DONE]":
        return {"__done__": True}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        log.debug("malformed SSE chunk ignored")
        return None


def _delta_text(chunk: dict[str, Any]) -> tuple[str, str, str | None]:
    """Return (content_delta, reasoning_delta, finish_reason) from a parsed chunk.

    Reasoning models (llama.cpp / LM Studio streaming) emit their chain of
    thought in ``delta.reasoning_content`` (or ``delta.reasoning``) and the
    final answer in ``delta.content``. Keep the two separate: reasoning-only
    replies are unfinished answers, not candidates for grading.
    """
    choices = chunk.get("choices") or []
    if not choices:
        return "", "", None
    choice = choices[0]
    delta = choice.get("delta") or {}
    content = delta.get("content") or ""
    if not isinstance(content, str):
        content = str(content)
    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or ""
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    finish = choice.get("finish_reason")
    return content, reasoning, finish


def _extract_usage(chunk: dict[str, Any]) -> dict[str, Any] | None:
    usage = chunk.get("usage")
    if isinstance(usage, dict):
        return usage
    return None


def _extract_content_nonstream(data: dict[str, Any]) -> tuple[str, str]:
    choices = data.get("choices") or []
    if not choices:
        return "", "unknown"
    choice = choices[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if not isinstance(content, str):
        content = json.dumps(content)
    return content, choice.get("finish_reason") or "unknown"


async def stream_chat(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> AsyncIterator[tuple[str, str, str | None, dict[str, Any] | None, dict[str, Any] | None]]:
    """Yield (content_delta, reasoning_delta, finish_reason_or_None, usage_or_None, timings_or_None)."""
    async with client.stream("POST", url, headers=headers, json=body) as response:
        if response.status_code >= 400:
            text = await _read_response_text(response)
            raise OpenAIClientError(
                _error_from_body(text, response.status_code),
                status=response.status_code,
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        async for line in response.aiter_lines():
            chunk = _extract_stream_chunk(line)
            if chunk is None:
                continue
            if chunk.get("__done__"):
                if state is not None:
                    state["done_received"] = True
                return
            if chunk.get("error"):
                raise OpenAIClientError(_error_from_body(json.dumps(chunk), response.status_code),
                                        status=response.status_code)
            choices = chunk.get("choices") or []
            if state is not None and choices:
                delta = choices[0].get("delta") or {}
                if delta.get("tool_calls") or delta.get("function_call"):
                    state["native_tool_calls_received"] = True
            content, reasoning, finish = _delta_text(chunk)
            usage = _extract_usage(chunk)
            timings = chunk.get("timings")
            yield content, reasoning, finish, usage, (timings if isinstance(timings, dict) else None)


async def _read_response_text(response: httpx.Response) -> str:
    try:
        return await response.aread()
    except Exception:
        return ""


def _error_from_body(text: str | bytes, status: int) -> str:
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8", errors="replace")
        except Exception:
            text = str(text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or str(err)
                return f"HTTP {status}: {_sanitize_error_message(str(msg))}"
            if isinstance(err, str):
                return f"HTTP {status}: {_sanitize_error_message(err)}"
            return f"HTTP {status}: {_sanitize_error_message(str(data))}"
    except json.JSONDecodeError:
        pass
    snippet = (text or "")[:200]
    return f"HTTP {status}: {_sanitize_error_message(snippet)}"


def _should_drop_stream_options(exc: OpenAIClientError, body: dict[str, Any]) -> bool:
    """True when a 4xx might be caused by our ``stream_options`` request.

    Deliberately broad: any client error while we are sending the field is
    treated as possibly caused by it, because servers that reject unknown
    fields often do so with a generic message ("extra inputs are not
    permitted") that never names the culprit. Matching only on the field name
    would turn those servers' every prompt into a hard failure -- a worse
    outcome than one wasted request on a genuinely bad request.

    This can fire at most once per call: the caller removes the field before
    retrying, so the ``in body`` guard is false forever after. 401/403 are
    excluded since an auth failure is never about the request body.
    """
    if "stream_options" not in body:
        return False
    if exc.status is None or not (400 <= exc.status < 500):
        return False
    return exc.status not in (401, 403, 404, 429)


async def chat_completion(
    base_url: str,
    *,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    stop: list[str] | None = None,
    seed: int | None = None,
    stream: bool = True,
    custom_headers: dict[str, str] | None = None,
    extra_body: dict[str, Any] | None = None,
    timeout: float = 60.0,
    verify_tls: bool = True,
    max_retries: int = 3,
    backoff_base: float = 0.5,
    backoff_max: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
) -> ChatResult:
    """Complete with network inactivity timeouts and bounded retries.

    Active streams may generate for longer than timeout; no total deadline
    is imposed on a question.
    """
    url = chat_completions_url(base_url)
    headers = _build_headers(api_key, custom_headers)
    body = _build_body(
        messages,
        model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=stop,
        seed=seed,
        stream=stream,
        extra_body=extra_body,
    )
    last_error: OpenAIClientError | None = None
    retry_count = 0
    first_attempt_at = time.monotonic()

    attempt = 0
    while attempt <= max_retries:
        # Time each attempt from its own start. Measuring from the first attempt
        # would fold failed requests and backoff sleeps into TTFT and latency,
        # making a model look arbitrarily slow whenever the server hiccuped.
        start = time.monotonic()
        try:
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
            async with httpx.AsyncClient(
                timeout=timeout,
                verify=verify_tls,
                limits=limits,
                transport=transport,
            ) as client:
                if stream:
                    result = await _do_stream(
                        client, url, headers, body, retry_count=attempt, start=start, on_progress=on_progress
                    )
                else:
                    result = await _do_nonstream(
                        client, url, headers, body, retry_count=attempt, start=start
                    )
                result.wall_time = time.monotonic() - first_attempt_at
                return result
        except OpenAIClientError as exc:
            last_error = exc
            # Some older/stricter servers reject the usage request outright.
            # Drop it and retry immediately rather than failing the prompt --
            # we lose exact token counts, not the measurement itself.
            if _should_drop_stream_options(exc, body):
                # Not the model's fault and not a transient failure: retry at
                # once without spending an attempt, so this still works when
                # max_retries is 0.
                log.info("server rejected stream_options; retrying without it")
                body.pop("stream_options", None)
                continue
            if not exc.retryable or attempt >= max_retries:
                retry_count = attempt
                break
            retry_count = attempt + 1
            delay = min(backoff_max, backoff_base * (2**attempt))
            log.warning(
                "retryable error (attempt %d): %s; retrying in %.1fs", attempt + 1, exc, delay
            )
            await asyncio.sleep(delay)
        except RETRYABLE_EXCEPTIONS as exc:
            last_error = OpenAIClientError(_sanitize_error_message(f"{type(exc).__name__}: {exc}"), retryable=True)
            if attempt >= max_retries:
                retry_count = attempt
                break
            retry_count = attempt + 1
            delay = min(backoff_max, backoff_base * (2**attempt))
            log.warning("retryable network error (attempt %d): %s", attempt + 1, exc)
            await asyncio.sleep(delay)
        except Exception as exc:  # permanent, non-retryable
            last_error = OpenAIClientError(_sanitize_error_message(str(exc)), retryable=False)
            retry_count = attempt
            break
        attempt += 1

    # All retries exhausted.
    total = time.monotonic() - first_attempt_at
    if last_error is None:
        last_error = OpenAIClientError("unknown error", retryable=False)
    return ChatResult(
        content="",
        finish_reason="error",
        truncated=False,
        usage={},
        http_status=last_error.status or 0,
        time_to_first_token=None,
        total_response_time=total,
        retry_count=retry_count,
        error=last_error.sanitized_message,
        raw={"error": last_error.sanitized_message},
        wall_time=total,
    )


async def _do_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    retry_count: int,
    start: float,
    on_progress: Callable[[dict], Awaitable[None]] | None = None,
) -> ChatResult:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = "unknown"
    ttft: float | None = None
    first_chunk_at: float | None = None
    usage: dict[str, Any] = {}
    timings: dict[str, Any] | None = None
    raw_chunks: list[dict[str, Any]] = []
    last_progress = 0.0
    stream_error = None
    state = {"done_received": False, "native_tool_calls_received": False}
    try:
        async for content, reasoning, finish, chunk_usage, chunk_timings in stream_chat(
            client, url, headers, body, state=state
        ):
            if first_chunk_at is None and (content or reasoning):
                first_chunk_at = time.monotonic()
                ttft = first_chunk_at - start
            if content:
                content_parts.append(content)
            if reasoning:
                reasoning_parts.append(reasoning)
            if finish:
                finish_reason = finish
            if chunk_usage:
                usage = chunk_usage
            if chunk_timings:
                timings = chunk_timings
            # Keep last few chunks for diagnostics, stripped of any token-bearing content.
            if len(raw_chunks) < 5:
                raw_chunks.append({"finish_reason": finish, "has_usage": bool(chunk_usage)})
            now = time.monotonic()
            if on_progress and now - last_progress >= 1:
                last_progress = now
                try:
                    await on_progress({
                        **generation_diagnostics("".join(content_parts), "".join(reasoning_parts), finish_reason),
                        "elapsed_seconds": now - start,
                        "retry_count": retry_count,
                    })
                except Exception:
                    log.exception("generation progress callback failed")
    except RETRYABLE_EXCEPTIONS as exc:
        if not (content_parts or reasoning_parts):
            raise
        stream_error = _sanitize_error_message(str(exc) or type(exc).__name__)
    except OpenAIClientError as exc:
        if not (content_parts or reasoning_parts):
            raise
        stream_error = exc.sanitized_message
    total = time.monotonic() - start
    content = "".join(content_parts)
    reasoning_text = "".join(reasoning_parts)
    no_final = not content.strip()
    truncated = finish_reason == "length"
    incomplete = finish_reason == "unknown" and not state["done_received"]
    diagnostics = generation_diagnostics(content, reasoning_text, finish_reason)
    diagnostics.update(state, incomplete_stream=incomplete,
                       finish_reason_received=finish_reason != "unknown", usage_received=bool(usage))
    error = stream_error
    if not error and incomplete:
        error = "Endpoint stream ended without a finish_reason or [DONE]; generation was incomplete."
    if not error and state["native_tool_calls_received"]:
        error = "Endpoint returned native tool_calls instead of answer text; this text-format benchmark requires a pass-through endpoint."
    if not error and no_final:
        error = "No final answer returned; reasoning is retained separately."
    if error:
        diagnostics["failure_category"] = (
            "incomplete_stream" if incomplete else
            "native_tool_calls" if state["native_tool_calls_received"] else
            "endpoint_error" if stream_error else "no_final_answer"
        )
    return ChatResult(
        content=content,
        finish_reason=finish_reason,
        truncated=truncated,
        usage=usage,
        http_status=200,
        time_to_first_token=ttft,
        total_response_time=total,
        retry_count=retry_count,
        raw={"streamed": True, "chunk_sample": raw_chunks, "fell_back_to_reasoning": False,
             "generation_diagnostics": diagnostics},
        reasoning=reasoning_text,
        error=error,
        server_timings=timings,
    )


async def _do_nonstream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    retry_count: int,
    start: float,
) -> ChatResult:
    # Force stream off in body for non-streaming requests.
    body = {**body, "stream": False}
    response = await client.post(url, headers=headers, json=body)
    total = time.monotonic() - start
    if response.status_code >= 400:
        raise OpenAIClientError(
            _error_from_body(response.content, response.status_code),
            status=response.status_code,
            retryable=response.status_code in RETRYABLE_STATUS,
        )
    try:
        data = response.json()
    except json.JSONDecodeError:
        raise OpenAIClientError("invalid JSON response from server", status=200)
    content, finish_reason = _extract_content_nonstream(data)
    choices = data.get("choices") or []
    message = choices[0].get("message", {}) if choices else {}
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    usage = data.get("usage") if isinstance(data, dict) else {}
    if not isinstance(usage, dict):
        usage = {}
    timings = data.get("timings") if isinstance(data, dict) else None
    truncated = finish_reason == "length"
    native_calls = bool(message.get("tool_calls") or message.get("function_call"))
    diagnostics = generation_diagnostics(content, reasoning, finish_reason)
    diagnostics["native_tool_calls_received"] = native_calls
    error = None
    if native_calls:
        error = "Endpoint returned native tool_calls instead of answer text; this text-format benchmark requires a pass-through endpoint."
        diagnostics["failure_category"] = "native_tool_calls"
    elif not content.strip():
        error = "No final answer returned; reasoning is retained separately."
        diagnostics["failure_category"] = "no_final_answer"
    # TTFT unavailable for non-streaming.
    return ChatResult(
        content=content,
        finish_reason=finish_reason,
        truncated=truncated,
        usage=usage,
        http_status=response.status_code,
        time_to_first_token=None,
        total_response_time=total,
        retry_count=retry_count,
        raw={"streamed": False, "generation_diagnostics": diagnostics},
        reasoning=reasoning,
        error=error,
        server_timings=timings if isinstance(timings, dict) else None,
    )
