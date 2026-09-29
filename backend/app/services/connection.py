"""Connection testing and model discovery for endpoint profiles."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.secrets import MISSING_SAVED_KEY
from app.core.security import sanitize
from app.core.urls import models_url
from app.models import EndpointProfile
from app.schemas import ConnectionTestResult, FetchModelsResult
from app.services.openai_client import _build_headers, chat_completion

log = logging.getLogger(__name__)


def _resolve_key(profile: EndpointProfile, session_key: str | None) -> str | None:
    if session_key:
        return session_key
    from app.core.secrets import resolve_api_key

    key, _source = resolve_api_key(
        profile.id,
        stored_value=profile.has_api_key,
        env_var=profile.api_key_env_var or None,
        session_key=None,
    )
    return key


def _sanitize_models(data: Any) -> list[str]:
    names: list[str] = []
    if isinstance(data, dict):
        models = data.get("data") or data.get("models") or []
        if isinstance(models, list):
            for m in models:
                if isinstance(m, dict):
                    mid = m.get("id") or m.get("name")
                    if mid:
                        names.append(str(mid))
                elif isinstance(m, str):
                    names.append(m)
    return names


async def fetch_models(
    profile: EndpointProfile, session_key: str | None = None
) -> FetchModelsResult:
    url = models_url(profile.base_url)
    key = _resolve_key(profile, session_key)
    if profile.has_api_key and not key:
        return FetchModelsResult(success=False, error=MISSING_SAVED_KEY)
    headers = _build_headers(key, profile.custom_headers, base_url=profile.base_url)
    try:
        async with httpx.AsyncClient(
            timeout=profile.request_timeout, verify=profile.verify_tls
        ) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code >= 400:
            return FetchModelsResult(
                success=False,
                error=f"HTTP {resp.status_code}: {_snippet(resp.content)}",
            )
        data = resp.json()
        models = _sanitize_models(data)
        if not models:
            return FetchModelsResult(success=False, error="No models returned by server.")
        return FetchModelsResult(success=True, models=sorted(set(models)))
    except Exception as exc:
        return FetchModelsResult(success=False, error=sanitize(str(exc)))


async def test_connection(
    profile: EndpointProfile, session_key: str | None = None
) -> ConnectionTestResult:
    """Verify the endpoint end-to-end.

    Many local servers leave GET /models open while requiring auth on
    /chat/completions, so a models-only check gives false confidence. This
    reaches the server (models) AND probes a real one-token completion, which
    catches missing/invalid API keys and bad model names before a run does.
    """
    url = models_url(profile.base_url)
    key = _resolve_key(profile, session_key)
    if profile.has_api_key and not key:
        return ConnectionTestResult(reachable=False, http_status=None, response_time_ms=None,
                                    models_discovered=False, error=MISSING_SAVED_KEY)
    headers = _build_headers(key, profile.custom_headers, base_url=profile.base_url)
    start = time.monotonic()
    http_status: int | None = None
    try:
        async with httpx.AsyncClient(
            timeout=profile.request_timeout, verify=profile.verify_tls
        ) as client:
            resp = await client.get(url, headers=headers)
        elapsed = (time.monotonic() - start) * 1000.0
        http_status = resp.status_code
        if resp.status_code >= 400:
            return ConnectionTestResult(
                reachable=True,
                http_status=resp.status_code,
                response_time_ms=round(elapsed, 1),
                models_discovered=False,
                error=f"HTTP {resp.status_code}: {_snippet(resp.content)}",
            )
        data = resp.json()
        models = _sanitize_models(data)
    except httpx.ConnectError as exc:
        return ConnectionTestResult(
            reachable=False, http_status=http_status, response_time_ms=None,
            models_discovered=False, error=f"Connection failed: {sanitize(str(exc))}",
        )
    except httpx.TimeoutException:
        return ConnectionTestResult(
            reachable=False, http_status=http_status, response_time_ms=None,
            models_discovered=False, error="Request timed out",
        )
    except Exception as exc:
        return ConnectionTestResult(
            reachable=False, http_status=http_status, response_time_ms=None,
            models_discovered=False, error=sanitize(str(exc)),
        )

    # Reached the server and listed models — now probe a real completion.
    model = profile.default_model or (models[0] if models else "")
    completion_ok = False
    completion_error: str | None = None
    if model:
        probe = await chat_completion(
            profile.base_url,
            api_key=key,
            model=model,
            messages=[{"role": "user", "content": "Reply with: ok"}],
            max_tokens=1,
            stream=False,
            custom_headers=profile.custom_headers,
            extra_body=profile.extra_body_params,
            timeout=min(profile.request_timeout, 20.0),
            verify_tls=profile.verify_tls,
            max_retries=0,
        )
        completion_ok = not probe.error
        completion_error = probe.error
    else:
        completion_error = "No model to test — set a Default model on this endpoint."

    return ConnectionTestResult(
        reachable=True,
        http_status=http_status,
        response_time_ms=round(elapsed, 1),
        models_discovered=bool(models),
        model_count=len(models),
        models=sorted(set(models))[:200],
        completion_checked=True,
        completion_ok=completion_ok,
        completion_model=model or None,
        error=None if completion_ok else completion_error,
    )


def _snippet(content: bytes | str, limit: int = 200) -> str:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8", errors="replace")
        except Exception:
            content = str(content)
    content = (content or "")[:limit]
    # Drop any embedded secrets.
    return str(sanitize(content))
