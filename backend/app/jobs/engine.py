"""Benchmark execution engine.

Runs entirely in the backend process so the browser may close/refresh.
Persists after every prompt, supports cancellation between requests, and
resumes interrupted jobs from the first incomplete prompt.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.tokens import estimate_tokens
from app.db.session import session_scope
from app.graders import scoring
from app.graders.deterministic import run_deterministic
from app.graders.execution import run_execution
from app.graders.judge_protocol import (
    build_judge_messages,
    build_repair_message,
    build_verifier_messages,
    judge_output_to_dict,
    parse_judge_output,
    parse_verifier_output,
)
from app.jobs.event_bus import bus
from app.models import (
    BenchmarkRun,
    DeterministicGrade,
    EndpointProfile,
    JudgeGrade,
    PerformanceMetric,
    PromptExecution,
    PromptStatus,
    RunStatus,
    TargetResponse,
    VerifierGrade,
)
from app.services.native_tools import native_request, normalize_native_result
from app.services.openai_client import ChatResult, chat_completion
from app.services.tool_compatibility import (
    annotate_text_tool_failure,
    requires_text_tool_calls,
    select_tool_protocol,
)

log = logging.getLogger(__name__)

TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_ERRORS.value,
    RunStatus.CANCELLED.value,
    RunStatus.FAILED.value,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Job creation
# --------------------------------------------------------------------------- #
def create_run_executions(
    session: Session,
    run: BenchmarkRun,
    benchmark_snapshot: dict[str, Any],
    repetitions: int,
    shuffle: bool,
) -> None:
    """Create PromptExecution rows for every enabled prompt x repetition."""
    prompts = [p for p in benchmark_snapshot.get("prompts", []) if p.get("enabled", True)]
    order = list(range(len(prompts)))
    if shuffle:
        random.shuffle(order)
    position = 0
    for idx in order:
        prompt = prompts[idx]
        for rep in range(1, repetitions + 1):
            execution = PromptExecution(
                id=str(uuid.uuid4()),
                run_id=run.id,
                prompt_snapshot_id=prompt.get("stable_id") or prompt.get("id", ""),
                repetition=rep,
                position=position,
                status=PromptStatus.PENDING.value,
                prompt_snapshot={
                    **prompt,
                    "messages": prompt.get("messages", []),
                },
                max_score=100.0,
            )
            session.add(execution)
            position += 1
    run.total_prompts = position
    run.completed_prompts = 0
    run.failed_prompts = 0


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #
def mark_interrupted_active_runs(session: Session) -> int:
    """On startup, mark any non-terminal runs as INTERRUPTED (crash recovery).

    Flushes so callers using a shared session see the change; the surrounding
    transaction commits at the end of the session scope.
    """
    active = (
        session.query(BenchmarkRun)
        .filter(~BenchmarkRun.status.in_(list(TERMINAL_STATUSES)))
        .all()
    )
    count = 0
    for run in active:
        run.status = RunStatus.INTERRUPTED.value
        run.error_message = (
            run.error_message or "Application stopped before the run completed."
        )
        count += 1
    if count:
        session.flush()
    return count


# --------------------------------------------------------------------------- #
# Async execution loop
# --------------------------------------------------------------------------- #
class JobCancelled(Exception):
    pass


# Immediate cancellation: a per-run asyncio.Event that request_cancel sets the
# moment a cancel is requested. In-flight HTTP requests race against it and are
# aborted on the spot instead of running to completion.
_cancel_events: dict[str, asyncio.Event] = {}
_cancel_event_loops: dict[str, asyncio.AbstractEventLoop] = {}


def get_cancel_event(run_id: str) -> asyncio.Event:
    """Return (creating if needed) the cancel event for a run.

    asyncio.Event objects are bound to the loop they were created on, so if the
    stored event belongs to a different loop (e.g. a fresh loop after an app or
    test restart) it is recreated rather than reused across loops.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    ev = _cancel_events.get(run_id)
    if ev is None or (loop is not None and _cancel_event_loops.get(run_id) is not loop):
        ev = asyncio.Event()
        _cancel_events[run_id] = ev
        _cancel_event_loops[run_id] = loop
    return ev


def signal_cancel(run_id: str) -> None:
    """Set the cancel event. Runs on the asyncio loop thread."""
    get_cancel_event(run_id).set()


def clear_cancel(run_id: str) -> None:
    _cancel_events.pop(run_id, None)
    _cancel_event_loops.pop(run_id, None)


async def _await_abortable(awaitable, run_id):
    """Await a coroutine, aborting it immediately if a cancel is signaled.

    Cancelling the in-flight task closes the httpx stream/connection at once, so
    a run stops right away even if the current request is hung or very slow.
    """
    task = asyncio.create_task(awaitable)
    cancel_waiter = asyncio.create_task(get_cancel_event(run_id).wait())
    try:
        done, _ = await asyncio.wait(
            {task, cancel_waiter}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_waiter in done:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise JobCancelled()
        return task.result()
    finally:
        # Parent cancellation (e.g. app shutdown) must also close the request.
        for pending in (task, cancel_waiter):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, cancel_waiter, return_exceptions=True)


async def _is_cancelled(session: Session, run_id: str) -> bool:
    run = session.get(BenchmarkRun, run_id)
    return run is not None and run.status in {
        RunStatus.CANCEL_REQUESTED.value,
        RunStatus.CANCELLED.value,
    }


async def run_job(
    run_id: str,
    *,
    target_profile: EndpointProfile,
    target_model: str,
    target_session_key: str | None,
    target_settings: dict[str, Any],
    judge_profile: EndpointProfile | None,
    judge_model: str,
    judge_session_key: str | None,
    judge_settings: dict[str, Any],
    run_config: dict[str, Any],
    judge_enabled: bool,
    verifier_enabled: bool,
) -> None:
    """Execute a single benchmark job to completion (or cancel/fail)."""
    log.info("Starting run %s", run_id)
    started_at = _now()
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return
        run.started_at = run.started_at or started_at
        run.status = RunStatus.PREPARING.value
        run.error_message = ""
    await _emit(run_id, "phase", phase="preparing")

    try:
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            needs_text_tools = any(requires_text_tool_calls(p) for p in
                                   (run.benchmark_snapshot or {}).get("prompts", [])
                                   if p.get("enabled", True))
        if needs_text_tools and not run_config.get("tool_call_protocol"):
            await _emit(run_id, "phase", phase="checking_text_tool_compatibility")
            extra_body = dict(target_profile.extra_body_params or {})
            effort = _pick({}, target_settings, run_config, "reasoning_effort")
            if effort:
                extra_body["chat_template_kwargs"] = {
                    **(extra_body.get("chat_template_kwargs") or {}), "reasoning_effort": effort,
                }
            compatibility = await _await_abortable(select_tool_protocol(
                target_profile, target_model, _resolve_key(target_profile, target_session_key),
                run_config, extra_body,
            ), run_id)
            run_config = {**run_config, "tool_call_protocol": compatibility.get("protocol", "text")}
            with session_scope() as session:
                run = session.get(BenchmarkRun, run_id)
                run.benchmark_snapshot = {**run.benchmark_snapshot, "text_tool_compatibility": compatibility}
                run.run_config = {**run.run_config, "tool_call_protocol": run_config["tool_call_protocol"]}
            await _emit(run_id, "compatibility", **compatibility)
        if run_config.get("warm_up_request"):
            await _warmup(run_id, target_profile, target_model, target_session_key,
                          target_settings, run_config)

        await _run_target_phase(
            run_id, target_profile, target_model, target_session_key,
            target_settings, run_config,
        )
        await _run_grading_phase(
            run_id,
            judge_enabled=judge_enabled,
            judge_profile=judge_profile,
            judge_model=judge_model,
            judge_session_key=judge_session_key,
            judge_settings=judge_settings,
            verifier_enabled=verifier_enabled,
            run_config=run_config,
        )
        await _finalize_run(run_id, error=False)
    except JobCancelled:
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is not None:
                run.status = RunStatus.CANCELLED.value
                run.completed_at = _now()
        await _emit(run_id, "cancelled", status=RunStatus.CANCELLED.value)
        log.info("Run %s cancelled", run_id)
    except Exception as exc:
        log.exception("Run %s failed", run_id)
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED.value
                run.error_message = str(exc)[:2000]
                run.completed_at = _now()
        await _emit(run_id, "failed", status=RunStatus.FAILED.value, message=str(exc)[:500])
    finally:
        bus.clear(run_id)
        clear_cancel(run_id)


async def _warmup(run_id, profile, model, session_key, settings, run_config):
    await _emit(run_id, "phase", phase="warming_up")
    try:
        await _await_abortable(chat_completion(
            profile.base_url,
            api_key=_resolve_key(profile, session_key),
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=8,
            stream=run_config.get("streaming_enabled", True),
            custom_headers=profile.custom_headers,
            extra_body=_limit_extra_body(profile.extra_body_params, 8),
            timeout=min(profile.request_timeout, 30.0),
            verify_tls=profile.verify_tls,
            max_retries=1,
        ), run_id)
    except Exception as exc:
        log.warning("warm-up request failed for run %s: %s", run_id, exc)


async def _run_target_phase(
    run_id, profile, model, session_key, settings, run_config
):
    await _emit(run_id, "phase", phase="running_target", status=RunStatus.RUNNING_TARGET.value)
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        run.status = RunStatus.RUNNING_TARGET.value
        # Read snapshotted pricing so historical costs are immutable.
        target_snapshot = (run.benchmark_snapshot or {}).get("target", {})
        input_price = float(target_snapshot.get("input_price_per_1m", 0.0) or 0.0)
        output_price = float(target_snapshot.get("output_price_per_1m", 0.0) or 0.0)
    while True:
        with session_scope() as session:
            if await _is_cancelled(session, run_id):
                raise JobCancelled()
            execution = (
                session.query(PromptExecution)
                .filter(PromptExecution.run_id == run_id)
                .filter(PromptExecution.status == PromptStatus.PENDING.value)
                .order_by(PromptExecution.position)
                .first()
            )
            if execution is None:
                break
            prompt_snapshot = dict(execution.prompt_snapshot)
            exec_id = execution.id
            execution.status = PromptStatus.RUNNING.value

        await _emit(
            run_id, "prompt_started",
            current_prompt=prompt_snapshot.get("title") or prompt_snapshot.get("stable_id"),
        )
        # Run the target request outside the session lock.
        result = await _execute_target_prompt(
            run_id, profile, model, session_key, settings, run_config, prompt_snapshot
        )
        with session_scope() as session:
            execution = session.get(PromptExecution, exec_id)
            _store_target_result(session, execution, result,
                                input_price_per_1m=input_price,
                                output_price_per_1m=output_price)
            _update_progress(session, run_id)
        await _emit_progress(run_id, execution_snapshot=prompt_snapshot, result=result)


async def _execute_target_prompt(run_id, profile, model, session_key, settings, run_config, prompt_snapshot):
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in prompt_snapshot.get("messages", [])
        if m.get("content") or m.get("role") == "system"
    ]
    overrides = prompt_snapshot.get("generation_overrides", {}) or {}
    temperature = _pick(overrides, settings, run_config, "temperature")
    top_p = _pick(overrides, settings, run_config, "top_p")
    max_tokens = run_config.get("max_tokens", 0)
    reasoning_effort = _pick(overrides, settings, run_config, "reasoning_effort")
    stop = overrides.get("stop")
    seed = overrides.get("seed")
    # llama.cpp/LM Studio accept a reasoning budget via the chat-template kwargs
    # (see the opencode provider config for the same servers). Surface it as a
    # run-level "reasoning level" option: low/medium/high/xhigh.
    extra_body = dict(profile.extra_body_params or {})
    native = run_config.get("tool_call_protocol") == "native" and requires_text_tool_calls(prompt_snapshot)
    if native:
        try:
            messages, tools = native_request(messages)
        except (ValueError, KeyError, TypeError) as exc:
            return ChatResult(content="", finish_reason="error", truncated=False, usage={}, http_status=0,
                              time_to_first_token=None, total_response_time=0, retry_count=0,
                              error=f"Cannot adapt this question to native tools: {exc}")
        extra_body.update(tools=tools, tool_choice="auto")
        for key in ("functions", "function_call", "messages", "model"):
            extra_body.pop(key, None)
    if reasoning_effort:
        chat_template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        chat_template_kwargs["reasoning_effort"] = reasoning_effort
        extra_body["chat_template_kwargs"] = chat_template_kwargs
    async def report_generation(fields):
        await _emit(run_id, "generation", **fields)

    result = await _await_abortable(chat_completion(
        profile.base_url,
        api_key=_resolve_key(profile, session_key),
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=stop,
        seed=seed,
        stream=run_config.get("streaming_enabled", True),
        custom_headers=profile.custom_headers,
        extra_body=_limit_extra_body(extra_body, max_tokens),
        timeout=run_config.get("timeout", profile.request_timeout),
        verify_tls=profile.verify_tls,
        max_retries=int(run_config.get("retry_max_attempts", 3)),
        backoff_base=float(run_config.get("retry_backoff_base", 0.5)),
        backoff_max=float(run_config.get("retry_backoff_max", 30.0)),
        on_progress=report_generation,
    ), run_id)
    if native:
        return normalize_native_result(result)
    if result.tool_calls and requires_text_tool_calls(prompt_snapshot):
        # Some endpoints convert text calls even without the tools parameter.
        return normalize_native_result(result)
    if result.tool_calls:
        result.error = "Unexpected native tool calls for a question without tools."
    result.raw["tool_call_protocol"] = "text" if requires_text_tool_calls(prompt_snapshot) else "chat"
    return annotate_text_tool_failure(result, prompt_snapshot)


def _limit_extra_body(extra_body, max_tokens):
    """Endpoint parameters cannot replace the global token limit."""
    body = dict(extra_body or {})
    body.pop("max_tokens", None)
    if "max_completion_tokens" in body:
        body.pop("max_completion_tokens")
        if max_tokens:
            body["max_completion_tokens"] = max_tokens
    return body


def _pick(overrides, settings, run_config, key):
    if key in overrides and overrides[key] is not None:
        return overrides[key]
    if key in settings and settings[key] is not None:
        return settings[key]
    return run_config.get(key)


def _resolve_key(profile, session_key):
    from app.core.secrets import resolve_api_key

    key, _ = resolve_api_key(
        profile.id,
        stored_value=profile.has_api_key,
        env_var=profile.api_key_env_var or None,
        session_key=session_key,
    )
    return key


def _positive_float(value: Any) -> float | None:
    """A usable positive rate, or None. Guards against nulls and junk values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _compute_cost(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    input_price_per_1m: float,
    output_price_per_1m: float,
) -> float | None:
    """Compute USD cost from token counts and per-1M-token pricing.

    Returns None when prices are unconfigured or a priced token count is
    unavailable, so the UI can distinguish "cost unknown" from "$0.00".
    """
    if input_price_per_1m <= 0 and output_price_per_1m <= 0:
        return None
    if ((input_price_per_1m > 0 and prompt_tokens is None)
            or (output_price_per_1m > 0 and completion_tokens is None)):
        return None
    pt = prompt_tokens or 0
    ct = completion_tokens or 0
    if pt == 0 and ct == 0:
        return None
    cost = (pt / 1_000_000.0) * input_price_per_1m + (ct / 1_000_000.0) * output_price_per_1m
    return round(cost, 8)


def _server_generation_rate(timings: dict[str, Any] | None) -> float | None:
    """Tokens/sec of pure generation as reported by the server, if it says.

    llama.cpp exposes ``predicted_per_second``; vLLM and others report nothing
    and we fall back to computing it client-side.
    """
    if not isinstance(timings, dict):
        return None
    return _positive_float(timings.get("predicted_per_second"))


def _server_prompt_rate(timings: dict[str, Any] | None) -> float | None:
    """Prefill (prompt processing) tokens/sec, when the server reports it."""
    if not isinstance(timings, dict):
        return None
    return _positive_float(timings.get("prompt_per_second"))


def _store_target_result(session: Session, execution: PromptExecution, result,
                         input_price_per_1m: float = 0.0,
                         output_price_per_1m: float = 0.0) -> None:
    diagnostics = result.raw.get("generation_diagnostics", {})
    response_meta = {
        "reasoning": result.reasoning,
        "generation_diagnostics": diagnostics,
        "wall_time": result.wall_time,
        "native_tool_calls": result.tool_calls,
        "answer_text": result.raw.get("answer_text", result.content),
        "tool_call_protocol": result.raw.get("tool_call_protocol", "chat"),
    }
    if result.error:
        session.add(TargetResponse(
            id=str(uuid.uuid4()), execution_id=execution.id,
            content=result.content or "", finish_reason=result.finish_reason,
            truncated=result.truncated, raw=response_meta,
        ))
        execution.status = PromptStatus.FAILED.value
        execution.error_message = result.error
        execution.completed_at = _now()
        usage = result.usage or {}
        metric = PerformanceMetric(
            id=str(uuid.uuid4()),
            execution_id=execution.id,
            request_start=_now_iso(),
            total_response_time=result.total_response_time,
            time_to_first_token=result.time_to_first_token,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            http_status=result.http_status or None,
            retry_count=result.retry_count,
            response_char_count=len(result.content or ""),
            truncated=result.truncated,
            finish_reason=result.finish_reason,
            cost=_compute_cost(
                prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
                input_price_per_1m=input_price_per_1m, output_price_per_1m=output_price_per_1m,
            ),
        )
        session.add(metric)
        return
    truncated = result.truncated
    content = result.content or ""
    usage = result.usage or {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    estimated = False
    if total_tokens is None and not prompt_tokens and not completion_tokens:
        completion_tokens = estimate_tokens(content)
        prompt_tokens = None
        total_tokens = completion_tokens
        estimated = True
    # Compute cost from snapshotted pricing.
    cost = _compute_cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_price_per_1m=input_price_per_1m,
        output_price_per_1m=output_price_per_1m,
    )
    # Output speed. Dividing tokens by total wall time folds in prompt
    # processing and network overhead, which understated a local llama.cpp run
    # by ~25%. When the server reports its own generation rate, that is the
    # honest number for "tokens per second" and we use it.
    tps = None
    tps_source = "computed"
    server_tps = _server_generation_rate(result.server_timings)
    if server_tps is not None:
        tps = server_tps
        tps_source = "server"
    elif completion_tokens and result.total_response_time and result.total_response_time > 0:
        tps = completion_tokens / result.total_response_time
    response = TargetResponse(
        id=str(uuid.uuid4()),
        execution_id=execution.id,
        content=content,
        finish_reason=result.finish_reason,
        truncated=truncated,
        raw={
            **response_meta,
            "usage_reported": bool(usage),
            "streamed": result.raw.get("streamed", False),
            "tps_source": tps_source,
            "prompt_tokens_per_second": _server_prompt_rate(result.server_timings),
        },
    )
    session.add(response)
    metric = PerformanceMetric(
        id=str(uuid.uuid4()),
        execution_id=execution.id,
        request_start=_now_iso(),
        time_to_first_token=result.time_to_first_token,
        total_response_time=result.total_response_time,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        tokens_estimated=estimated,
        output_tokens_per_second=tps,
        finish_reason=result.finish_reason,
        http_status=result.http_status,
        retry_count=result.retry_count,
        truncated=truncated,
        response_char_count=len(content),
        cost=cost,
    )
    session.add(metric)


def _update_progress(session: Session, run_id: str) -> None:
    run = session.get(BenchmarkRun, run_id)
    execs = (
        session.query(PromptExecution)
        .filter(PromptExecution.run_id == run_id)
        .all()
    )
    # An execution counts as "done" once generation produced a stored target
    # response, even though it still holds status RUNNING until the grading
    # phase picks it up. Without this the progress bar is frozen at 0 for the
    # entire target phase. Graded prompts are also counted by their terminal
    # status below.
    done_ids = {
        r.execution_id
        for r in session.query(TargetResponse)
        .filter(TargetResponse.execution_id.in_([e.id for e in execs]))
    }
    completed = sum(
        1 for e in execs
        if e.id in done_ids or e.status in {
            PromptStatus.COMPLETED.value,
            PromptStatus.AWAITING_MANUAL.value,
            PromptStatus.AWAITING_JUDGE.value,
            PromptStatus.FAILED.value,
        }
    )
    failed = sum(1 for e in execs if e.status == PromptStatus.FAILED.value)
    run.completed_prompts = completed
    run.failed_prompts = failed


async def _run_grading_phase(
    run_id, *, judge_enabled, judge_profile, judge_model, judge_session_key,
    judge_settings, verifier_enabled, run_config,
):
    # Deterministic first.
    await _emit(run_id, "phase", phase="running_deterministic", status=RunStatus.RUNNING_DETERMINISTIC.value)
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        run.status = RunStatus.RUNNING_DETERMINISTIC.value
        execs = (
            session.query(PromptExecution)
            .filter(PromptExecution.run_id == run_id)
            .filter(PromptExecution.status == PromptStatus.RUNNING.value)
            .all()
        )
        # Collect content strings while the session is open (avoid detached instances).
        target_contents = {}
        for e in execs:
            target = (
                session.query(TargetResponse)
                .filter(TargetResponse.execution_id == e.id)
                .first()
            )
            target_contents[e.id] = target.content if target else ""

    for exec_id, content in target_contents.items():
        with session_scope() as session:
            execution = session.get(PromptExecution, exec_id)
            if execution is None:
                continue
            if await _is_cancelled(session, run_id):
                raise JobCancelled()
            mode = execution.prompt_snapshot.get("grading_mode")
            if mode == "execution":
                # The execution grader shells out with a per-problem timeout;
                # it must not block the event loop, and the worker thread needs
                # its own session (SQLAlchemy sessions are not thread-safe).
                await asyncio.to_thread(_grade_execution, exec_id, content)
            else:
                _grade_deterministic(session, execution, content)

    # Judge + verifier.
    if judge_enabled and judge_profile is not None:
        await _emit(run_id, "phase", phase="running_judge", status=RunStatus.RUNNING_JUDGE.value)
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            run.status = RunStatus.RUNNING_JUDGE.value
        await _judge_phase(
            run_id, judge_profile, judge_model, judge_session_key,
            judge_settings, run_config, verifier_enabled,
        )
        # Any still-"running" prompts are manual-review prompts awaiting a human.
        with session_scope() as session:
            execs = (
                session.query(PromptExecution)
                .filter(PromptExecution.run_id == run_id)
                .filter(PromptExecution.status == PromptStatus.RUNNING.value)
                .all()
            )
            for execution in execs:
                execution.status = PromptStatus.AWAITING_MANUAL.value
                execution.completed_at = _now()
            _update_progress(session, run_id)
    else:
        # Mark judge-required prompts awaiting.
        with session_scope() as session:
            execs = (
                session.query(PromptExecution)
                .filter(PromptExecution.run_id == run_id)
                .filter(PromptExecution.status == PromptStatus.RUNNING.value)
                .all()
            )
            for execution in execs:
                mode = execution.prompt_snapshot.get("grading_mode")
                if mode in {"judge", "hybrid"}:
                    execution.status = PromptStatus.AWAITING_JUDGE.value
                    execution.error_message = "Judge not configured; awaiting later judging."
                elif mode == "manual":
                    execution.status = PromptStatus.AWAITING_MANUAL.value
                else:
                    execution.status = PromptStatus.COMPLETED.value
            _update_progress(session, run_id)

    if verifier_enabled and judge_enabled and judge_profile is not None:
        await _emit(run_id, "phase", phase="running_verifier", status=RunStatus.RUNNING_VERIFIER.value)
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            run.status = RunStatus.RUNNING_VERIFIER.value
        await _verifier_phase(run_id, judge_profile, judge_model, judge_session_key, judge_settings, run_config)


def _grade_deterministic(session: Session, execution: PromptExecution, response: str) -> None:
    mode = execution.prompt_snapshot.get("grading_mode")
    grader_config = execution.prompt_snapshot.get("grader_config", {}) or {}
    if mode == "deterministic":
        result = run_deterministic(grader_config, response)
        grade = DeterministicGrade(
            id=str(uuid.uuid4()),
            execution_id=execution.id,
            grader_type="combined",
            passed=result["passed"],
            score=result["score"],
            max_score=result["max_score"],
            details={"checks": result.get("checks", [])},
        )
        session.add(grade)
        execution.final_score = float(result["score"])
        execution.max_score = float(result["max_score"])
        execution.status = PromptStatus.COMPLETED.value
        execution.completed_at = _now()
    elif mode == "hybrid":
        # Deterministic part; judge part filled later.
        det_config = {
            "checks": grader_config.get("deterministic_checks", []),
        }
        if grader_config.get("deterministic_checks"):
            result = run_deterministic(det_config, response)
            grade = DeterministicGrade(
                id=str(uuid.uuid4()),
                execution_id=execution.id,
                grader_type="hybrid_combined",
                passed=result["passed"],
                score=result["score"],
                max_score=result["max_score"],
                details={"checks": result.get("checks", [])},
            )
            session.add(grade)
            execution.final_score = float(result["score"])  # provisional; judge merges
        execution.status = PromptStatus.RUNNING.value  # still needs judge


def _prompt_text_from_snapshot(snapshot: dict) -> str:
    """The code prefix a completion prompt was written against.

    Execution prompts are completion tasks: the model continues the text of
    the user message(s). Joining the user messages in position order is the
    exact prompt for the single-message prompts (HumanEval) the mode targets.
    """
    msgs = sorted(snapshot.get("messages", []) or [], key=lambda m: m.get("position", 0))
    return "\n".join(m.get("content", "") for m in msgs if m.get("role") == "user")


def _grade_execution(exec_id: str, content: str) -> None:
    """Grade an execution-mode prompt. Runs in a worker thread, own session."""
    with session_scope() as session:
        execution = session.get(PromptExecution, exec_id)
        if execution is None:
            return
        snapshot = execution.prompt_snapshot or {}
        result = run_execution(
            snapshot.get("grader_config", {}) or {},
            content,
            _prompt_text_from_snapshot(snapshot),
        )
        grade = DeterministicGrade(
            id=str(uuid.uuid4()),
            execution_id=execution.id,
            grader_type="execution",
            passed=result["passed"],
            score=result["score"],
            max_score=result["max_score"],
            details=result.get("details", {}),
        )
        session.add(grade)
        execution.final_score = float(result["score"])
        execution.max_score = float(result["max_score"])
        execution.status = PromptStatus.COMPLETED.value
        execution.completed_at = _now()


async def _judge_phase(
    run_id, judge_profile, judge_model, judge_session_key, judge_settings,
    run_config, verifier_enabled,
):
    with session_scope() as session:
        execs = (
            session.query(PromptExecution)
            .filter(PromptExecution.run_id == run_id)
            .filter(PromptExecution.status == PromptStatus.RUNNING.value)
            .all()
        )
        candidates = []
        for e in execs:
            mode = e.prompt_snapshot.get("grading_mode")
            if mode in {"judge", "hybrid"}:
                target = (
                    session.query(TargetResponse)
                    .filter(TargetResponse.execution_id == e.id)
                    .first()
                )
                candidates.append((e.id, e.prompt_snapshot, target.content if target else ""))

    for exec_id, prompt_snapshot, candidate in candidates:
        if not candidate:
            continue
        with session_scope() as session:
            if await _is_cancelled(session, run_id):
                raise JobCancelled()
        judge_config = prompt_snapshot.get("grader_config", {}) or {}
        # For hybrid, the judge sub-config lives under "judge".
        if prompt_snapshot.get("grading_mode") == "hybrid":
            judge_config = judge_config.get("judge", judge_config)
        messages = build_judge_messages(
            original_messages=prompt_snapshot.get("messages", []),
            candidate_response=candidate,
            config=judge_config,
            extra_instructions=judge_config.get("judge_instructions", ""),
        )
        result = await _await_abortable(chat_completion(
            judge_profile.base_url,
            api_key=_resolve_key(judge_profile, judge_session_key),
            model=judge_model,
            messages=messages,
            temperature=judge_settings.get("temperature", 0.0),
            max_tokens=run_config.get("max_tokens", 0),
            stream=False,
            custom_headers=judge_profile.custom_headers,
            extra_body=_limit_extra_body(judge_profile.extra_body_params, run_config.get("max_tokens", 0)),
            timeout=run_config.get("timeout", judge_profile.request_timeout),
            verify_tls=judge_profile.verify_tls,
            max_retries=int(run_config.get("retry_max_attempts", 3)),
        ), run_id)
        await _store_judge_result(
            run_id, exec_id, prompt_snapshot, result, judge_config,
            candidate=candidate,
            judge_profile=judge_profile,
            judge_model=judge_model,
            judge_session_key=judge_session_key,
            judge_settings=judge_settings,
            run_config=run_config,
        )


async def _store_judge_result(
    run_id, exec_id, prompt_snapshot, result, judge_config,
    *, candidate, judge_profile, judge_model, judge_session_key, judge_settings, run_config,
):
    raw_text = result.content or ""
    parsed, err = parse_judge_output(raw_text)
    repair_attempted = False
    if parsed is None and result.content:
        # One repair attempt. Re-send the full task and the *actual* candidate
        # answer, include the judge's own invalid reply as an assistant turn,
        # and ask it to fix the JSON (each request is stateless, so the judge
        # only sees what we resend). Use the real judge endpoint + credentials.
        repair_attempted = True
        with session_scope() as session:
            if await _is_cancelled(session, run_id):
                raise JobCancelled()
        repair_messages = build_judge_messages(
            original_messages=prompt_snapshot.get("messages", []),
            candidate_response=candidate,
            config=judge_config,
            extra_instructions=judge_config.get("judge_instructions", ""),
        ) + [
            {"role": "assistant", "content": raw_text[:5000]},
            build_repair_message(err),
        ]
        repair_result = await _await_abortable(chat_completion(
            judge_profile.base_url,
            api_key=_resolve_key(judge_profile, judge_session_key),
            model=judge_model,
            messages=repair_messages,
            temperature=judge_settings.get("temperature", 0.0),
            max_tokens=run_config.get("max_tokens", 0),
            stream=False,
            custom_headers=judge_profile.custom_headers,
            extra_body=_limit_extra_body(judge_profile.extra_body_params, run_config.get("max_tokens", 0)),
            timeout=run_config.get("timeout", judge_profile.request_timeout),
            verify_tls=judge_profile.verify_tls,
            max_retries=0,
        ), run_id)
        parsed, err = parse_judge_output(repair_result.content or "")
        raw_text = repair_result.content or raw_text

    with session_scope() as session:
        execution = session.get(PromptExecution, exec_id)
        if execution is None:
            return
        if parsed is None:
            grade = JudgeGrade(
                id=str(uuid.uuid4()),
                execution_id=exec_id,
                final_score=0.0,
                valid=False,
                repair_attempted=repair_attempted,
                raw_response=raw_text[:5000],
                dimension_scores={},
                strengths=[],
                deductions=[],
                confidence=None,
            )
            session.add(grade)
            execution.status = PromptStatus.AWAITING_MANUAL.value
            execution.error_message = f"Judge output invalid: {err}"
            execution.final_score = None
            return
        data = judge_output_to_dict(parsed)
        grade = JudgeGrade(
            id=str(uuid.uuid4()),
            execution_id=exec_id,
            final_score=float(data["final_score"]),
            raw_total=float(data["raw_total"]),
            critical_error=bool(data["critical_error"]),
            score_cap=data["score_cap"],
            confidence=data["confidence"],
            dimension_scores=data["dimension_scores"],
            strengths=data["strengths"],
            deductions=data["deductions"],
            raw_response=raw_text[:5000],
            valid=True,
            repair_attempted=repair_attempted,
        )
        session.add(grade)
        # Hybrid: merge deterministic + judge.
        if prompt_snapshot.get("grading_mode") == "hybrid":
            det_grade = (
                session.query(DeterministicGrade)
                .filter(DeterministicGrade.execution_id == exec_id)
                .first()
            )
            det_fraction = (det_grade.score / det_grade.max_score) if det_grade and det_grade.max_score else 0.0
            judge_fraction = float(data["final_score"]) / 100.0
            grader_config = prompt_snapshot.get("grader_config", {}) or {}
            det_w = float(grader_config.get("deterministic_weight", 40.0))
            jud_w = float(grader_config.get("judge_weight", 60.0))
            merged = scoring.hybrid_score(
                deterministic_fraction=det_fraction,
                judge_fraction=judge_fraction,
                deterministic_weight=det_w,
                judge_weight=jud_w,
            )
            # Critical-fail caps.
            for cap_rule in grader_config.get("critical_fail_caps", []):
                if cap_rule.get("applies_when") == "invalid_json" and not det_grade:
                    merged = min(merged, float(cap_rule.get("cap", 40)))
            execution.final_score = merged
        else:
            execution.final_score = float(data["final_score"])
        execution.max_score = 100.0
        execution.status = PromptStatus.COMPLETED.value
        execution.completed_at = _now()


async def _verifier_phase(run_id, judge_profile, judge_model, judge_session_key, judge_settings, run_config):
    with session_scope() as session:
        execs = (
            session.query(PromptExecution)
            .filter(PromptExecution.run_id == run_id)
            .filter(PromptExecution.status == PromptStatus.COMPLETED.value)
            .all()
        )
        targets_map = {}
        for e in execs:
            t = session.query(TargetResponse).filter(TargetResponse.execution_id == e.id).first()
            j = session.query(JudgeGrade).filter(JudgeGrade.execution_id == e.id).first()
            if t and j and j.valid:
                targets_map[e.id] = (e.prompt_snapshot, t.content, j)

    for exec_id, (prompt_snapshot, candidate, judge_grade) in targets_map.items():
        with session_scope() as session:
            if await _is_cancelled(session, run_id):
                raise JobCancelled()
        judge_config = prompt_snapshot.get("grader_config", {}) or {}
        if prompt_snapshot.get("grading_mode") == "hybrid":
            judge_config = judge_config.get("judge", judge_config)
        messages = build_verifier_messages(
            original_messages=prompt_snapshot.get("messages", []),
            candidate_response=candidate,
            config=judge_config,
            judge_result={
                "final_score": judge_grade.final_score,
                "dimension_scores": judge_grade.dimension_scores,
                "deductions": judge_grade.deductions,
                "critical_error": judge_grade.critical_error,
            },
        )
        result = await _await_abortable(chat_completion(
            judge_profile.base_url,
            api_key=_resolve_key(judge_profile, judge_session_key),
            model=judge_model,
            messages=messages,
            temperature=judge_settings.get("temperature", 0.0),
            max_tokens=run_config.get("max_tokens", 0),
            stream=False,
            custom_headers=judge_profile.custom_headers,
            extra_body=_limit_extra_body(judge_profile.extra_body_params, run_config.get("max_tokens", 0)),
            timeout=run_config.get("timeout", judge_profile.request_timeout),
            verify_tls=judge_profile.verify_tls,
            max_retries=int(run_config.get("retry_max_attempts", 3)),
        ), run_id)
        parsed, err = parse_verifier_output(result.content or "")
        with session_scope() as session:
            execution = session.get(PromptExecution, exec_id)
            if execution is None:
                continue
            original = judge_grade.final_score
            if parsed is None:
                v = VerifierGrade(
                    id=str(uuid.uuid4()), execution_id=exec_id, original_score=original,
                    verified_score=original, adjusted=False, valid=False,
                    raw_response=(result.content or "")[:5000],
                    adjustment_reason=f"verifier output invalid: {err}",
                )
                session.add(v)
                continue
            verified = parsed.verified_score
            v = VerifierGrade(
                id=str(uuid.uuid4()),
                execution_id=exec_id,
                original_score=original,
                verified_score=verified,
                adjusted=parsed.adjusted or abs(verified - original) > 0.01,
                confidence=parsed.confidence,
                adjustment_reason=parsed.adjustment_reason,
                problems_found=parsed.problems_found,
                raw_response=(result.content or "")[:5000],
                valid=True,
            )
            session.add(v)
            # Use the verified score as the final judge score when valid.
            execution.final_score = float(verified)


async def _finalize_run(run_id: str, error: bool) -> None:
    summary = compute_run_summary(run_id)
    status = RunStatus.COMPLETED.value
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return
        run.summary = summary
        failed = run.failed_prompts
        if error and not failed:
            status = RunStatus.FAILED.value
        elif failed:
            status = RunStatus.COMPLETED_WITH_ERRORS.value
        run.status = status
        run.completed_at = _now()
    # Awaited, not fire-and-forget: run_job clears the bus immediately after it
    # returns, so a detached task could publish into an already-cleared bus (or
    # be garbage-collected before it ran) and the UI would never see the finish.
    await _emit(run_id, "completed", status=status, message="Run finished")


# --------------------------------------------------------------------------- #
# Summary computation (quality/reliability/performance/composite)
# --------------------------------------------------------------------------- #
def compute_run_summary(run_id: str) -> dict[str, Any]:
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return {}
        execs = (
            session.query(PromptExecution)
            .filter(PromptExecution.run_id == run_id)
            .all()
        )
        composite_weights = (run.benchmark_snapshot or {}).get("composite_weights", {}) or {}
        thresholds = (run.benchmark_snapshot or {}).get("performance_thresholds", {}) or {}
        # One query for every metric rather than one per execution.
        metrics_by_exec: dict[str, PerformanceMetric] = {}
        if execs:
            for m in (
                session.query(PerformanceMetric)
                .filter(PerformanceMetric.execution_id.in_([e.id for e in execs]))
                .all()
            ):
                metrics_by_exec.setdefault(m.execution_id, m)
        prompt_rows = []
        metrics_rows = []
        for e in execs:
            metric = metrics_by_exec.get(e.id)
            prompt_rows.append({
                "score": e.final_score,
                "weight": e.prompt_snapshot.get("importance_weight", 1.0),
                "status": e.status,
                "category": e.prompt_snapshot.get("category", "general"),
                "mode": e.prompt_snapshot.get("grading_mode"),
            })
            metrics_rows.append({
                "time_to_first_token": getattr(metric, "time_to_first_token", None) if metric else None,
                "output_tokens_per_second": getattr(metric, "output_tokens_per_second", None) if metric else None,
                "failed": e.status == PromptStatus.FAILED.value,
                "truncated": bool(getattr(metric, "truncated", False)) if metric else False,
                "retried": int(getattr(metric, "retry_count", 0) or 0) > 0 if metric else False,
                "empty_response": not (getattr(metric, "response_char_count", 0) or 0) if metric else True,
            })
        quality, scored, total = scoring.overall_quality_score(prompt_rows)
        repetition_scores = [e.final_score for e in execs if e.final_score is not None]
        repetition = scoring.repetition_stats(repetition_scores) if repetition_scores else {}
        # Reliability factors. Each must measure something distinct -- an
        # earlier version defined "structure" with the same expression as
        # "completion", which silently gave completion 0.45 of the weight and
        # let a genuinely malformed run score as if it were clean.
        n = max(1, len(prompt_rows))
        completion = sum(1 for r in prompt_rows if r["status"] != PromptStatus.FAILED.value) / n
        # Did the transport actually deliver a usable, non-empty body?
        valid_response = sum(1 for m in metrics_rows if not m["failed"] and not m["empty_response"]) / n
        # Did the answer land in a gradeable shape? A prompt that produced a
        # score is structurally sound; one that needed retries or came back
        # truncated is not, even when it eventually completed.
        structure = sum(
            1 for r, m in zip(prompt_rows, metrics_rows)
            if r["status"] != PromptStatus.FAILED.value
            and not m["truncated"]
            and not m["retried"]
        ) / n
        grade_parsed = scored / n
        truncated_count = sum(1 for m in metrics_rows if m["truncated"])
        no_truncation = 1.0 - (truncated_count / n)
        rel = scoring.reliability_score(
            {
                "completion": completion,
                "valid_response": valid_response,
                "structure": structure,
                "grade_parsed": grade_parsed,
                "no_truncation": no_truncation,
            },
            repetitions=max(1, int(run.run_config.get("repetitions", 1))),
            repetition_scores=repetition_scores if len(repetition_scores) >= 2 else None,
        )
        perf = scoring.performance_index(metrics=metrics_rows, thresholds=thresholds or {
            "desired_ttft": 0.5, "max_ttft": 5.0, "desired_tps": 40.0,
            "min_tps": 5.0, "max_failure_rate": 0.1,
        })
        comp = scoring.composite_score(
            quality=quality, reliability=rel, performance=perf,
            weights=composite_weights or None,
        )
        # Category breakdown.
        categories: dict[str, list[tuple[float, float]]] = {}
        for r in prompt_rows:
            if r["score"] is not None and r["status"] != PromptStatus.FAILED.value:
                categories.setdefault(r["category"], []).append((r["score"], r["weight"]))
        cat_scores = {c: scoring.category_quality_score(v) for c, v in categories.items()}
        # Aggregate cost across all executions.
        total_cost = None
        costs = [m.cost for m in metrics_by_exec.values() if m.cost is not None]
        # A partial sum would understate the total when usage is missing.
        if costs and len(costs) == len(execs):
            total_cost = round(sum(costs), 6)
        return {
            "quality_score": round(quality, 2) if quality is not None else None,
            "reliability_score": round(rel, 2),
            "performance_index": round(perf, 2),
            "composite_score": round(comp, 2) if comp is not None else None,
            "scoring_coverage": f"{scored} of {total} prompts",
            "scored_count": scored,
            "total_count": total,
            "category_scores": {k: round(v, 2) for k, v in cat_scores.items() if v is not None},
            "repetition": {k: (round(val, 3) if isinstance(val, float) else val) for k, val in repetition.items()},
            "total_cost": total_cost,
        }


# --------------------------------------------------------------------------- #
# Event emission
# --------------------------------------------------------------------------- #
async def _emit(run_id, event, **fields):
    evt = {"event": event, "run_id": run_id, "timestamp": _now_iso(), **fields}
    try:
        await bus.publish(run_id, evt)
    except Exception:
        log.exception("failed to publish event")


async def _emit_progress(run_id, execution_snapshot, result):
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        completed = run.completed_prompts
        total = run.total_prompts or 1
        failed = run.failed_prompts
    progress = completed / total
    await _emit(
        run_id, "prompt",
        status=run_status_for_emit(run_id),
        current_prompt=execution_snapshot.get("title") or execution_snapshot.get("stable_id"),
        completed=completed,
        total=total,
        progress=round(progress, 4),
        last_score=None,
        error_count=failed,
        message=("Prompt failed: " + result.error[:200]) if result.error else None,
    )


def run_status_for_emit(run_id):
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        return run.status if run else "unknown"
