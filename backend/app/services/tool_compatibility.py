"""Probe text tool-call transport without grading the model's tool selection."""
from __future__ import annotations

from app.services.openai_client import ChatResult, chat_completion

PROBE_TEXT = '<tool_call>{"name":"get_weather","arguments":{"location":"Paris","unit":"celsius"}}</tool_call>'
REMEDY = (
    "The endpoint may require native API tools rather than literal <tool_call> text. "
    "Tool questions can use the native protocol; unrelated questions can still run."
)


def requires_text_tool_calls(prompt: dict) -> bool:
    config = prompt.get("grader_config") or {}
    checks = config.get("checks", [config])
    return (any(check.get("type") == "tool_call" for check in checks)
            or any("<tools>" in m.get("content", "") for m in prompt.get("messages", []) if m.get("role") == "system"))


def classify_probe(result: ChatResult) -> dict:
    diagnostics = result.raw.get("generation_diagnostics") or {}
    error = result.error or ""
    parser_rejection = any(marker in error.lower() for marker in (
        "malformed tool call", "malformed tool_call", "invalid tool call",
        "failed to parse tool call", "tool-call parser", "tool call parser",
    ))
    if parser_rejection or diagnostics.get("native_tool_calls_received"):
        return {"status": "incompatible", "message": f"Endpoint requires a different tool-call transport. {REMEDY}",
                "error": error, "http_status": result.http_status}
    # Model failure to copy is inconclusive, not evidence of endpoint rejection.
    if not result.error and result.content.strip() == PROBE_TEXT:
        status = "compatible"
        message = "Endpoint preserved the probe's literal <tool_call> text."
    else:
        status = "inconclusive"
        message = "Text tool-call compatibility could not be confirmed; benchmark questions will still run."
    return {"status": status, "message": message, "error": error or None,
            "http_status": result.http_status}


async def probe_text_tool_calls(profile, model, api_key, run_config, extra_body) -> dict:
    # This is a short unscored connection diagnostic, not a benchmark question.
    # Its separate deadline cannot limit an active scored generation.
    import asyncio

    token_limit = run_config.get("max_tokens", 0)
    diagnostic_limit = min(token_limit, 256) if token_limit > 0 else 256
    body = dict(extra_body)
    body.pop("max_tokens", None)
    if "max_completion_tokens" in body:
        body["max_completion_tokens"] = diagnostic_limit
    # Endpoint extras cannot replace the diagnostic's prompt or output budget.
    for key in ("messages", "model", "stop", "stream_options"):
        body.pop(key, None)
    try:
        result = await asyncio.wait_for(chat_completion(
            profile.base_url, api_key=api_key, model=model,
            messages=[{"role": "user", "content": f"Copy the following line exactly. Output only the line, without analysis or explanation:\n{PROBE_TEXT}"}],
            temperature=0.0, max_tokens=diagnostic_limit, stream=False,
            custom_headers=profile.custom_headers, extra_body=body,
            timeout=min(run_config.get("timeout", 60.0), 30.0),
            verify_tls=profile.verify_tls, max_retries=0,
        ), timeout=30.0)
    except asyncio.TimeoutError:
        return {"status": "inconclusive", "message": "Text tool-call compatibility probe exceeded its 30s diagnostic deadline; benchmark questions will still run."}
    return classify_probe(result)


async def select_tool_protocol(profile, model, api_key, run_config, extra_body) -> dict:
    """Find a usable transport; inability to probe must never block other questions."""
    import asyncio

    text_report = await probe_text_tool_calls(profile, model, api_key, run_config, extra_body)
    if text_report["status"] == "compatible":
        return {**text_report, "protocol": "text"}
    body = dict(extra_body)
    for key in ("messages", "model", "stop", "stream_options", "max_tokens", "functions", "function_call"):
        body.pop(key, None)
    limit = run_config.get("max_tokens", 0)
    budget = min(limit, 256) if limit > 0 else 256
    if "max_completion_tokens" in body:
        body["max_completion_tokens"] = budget
    body["tools"] = [{"type": "function", "function": {
        "name": "get_weather", "description": "Get the current weather for a location.",
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
        }, "required": ["location", "unit"]},
    }}]
    body["tool_choice"] = "auto"
    try:
        result = await asyncio.wait_for(chat_completion(
            profile.base_url, api_key=api_key, model=model,
            messages=[{"role": "user", "content": "Use get_weather to get the weather in Paris in celsius. Return the tool call only."}],
            temperature=0.0, max_tokens=budget, stream=False, extra_body=body,
            custom_headers=profile.custom_headers, verify_tls=profile.verify_tls,
            timeout=min(run_config.get("timeout", 60), 30), max_retries=0,
        ), timeout=30)
    except asyncio.TimeoutError:
        result = None
    # A native response proves support. An accepted HTTP 200 request can still
    # contain model failure, which belongs in scored questions rather than a gate.
    native_accepted = result is not None and result.http_status == 200
    protocol = "native" if native_accepted or text_report["status"] == "incompatible" else "text"
    return {
        "status": "compatible" if native_accepted and result.tool_calls and not result.error else "inconclusive",
        "protocol": protocol,
        "message": ("Using native API tool calls for tool questions; other questions use ordinary chat."
                    if protocol == "native" else "Tool compatibility probe was inconclusive; questions will still run using text tools."),
        "text_probe": text_report,
        "native_probe_error": result.error if result is not None else "Native diagnostic exceeded 30s",
    }


def annotate_text_tool_failure(result: ChatResult, prompt: dict) -> ChatResult:
    """Explain an abrupt text-tool response without claiming its cause is proven."""
    if not requires_text_tool_calls(prompt):
        return result
    diagnostics = result.raw.get("generation_diagnostics") or {}
    if classify_probe(result)["status"] == "incompatible":
        result.error = f"Endpoint rejected or converted the text tool-call response. {REMEDY} Original error: {result.error}"
        diagnostics["failure_category"] = "text_tool_call_incompatibility"
    elif diagnostics.get("incomplete_stream") and not result.content.strip():
        diagnostics["possible_tool_parser_abort"] = True
        result.error = (
            "Endpoint closed a text tool-call response without a finish_reason or [DONE]. "
            "A server-side tool-call parser may have aborted generation. "
            f"{REMEDY} Original error: {result.error}"
        )
    result.raw["generation_diagnostics"] = diagnostics
    return result
