"""Tests for job persistence, interrupted-run recovery, and resume behavior."""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.db.session import session_scope
from app.jobs import engine
from app.jobs.engine import (
    create_run_executions,
    mark_interrupted_active_runs,
)
from app.jobs.runner import request_cancel, resume_run
from app.models import (
    BenchmarkRun,
    EndpointProfile,
    PromptExecution,
    PromptStatus,
    RunStatus,
)
from app.services import crud
from app.services.openai_client import ChatResult


def _make_endpoint(session, name="Local"):
    ep = EndpointProfile(
        id=str(uuid.uuid4()), name=name, base_url="http://127.0.0.1:11434/v1",
        default_model="demo", request_timeout=30.0, verify_tls=True,
        custom_headers={}, extra_body_params={}, enabled=True,
        has_api_key=False, api_key_storage="none", api_key_env_var="",
    )
    session.add(ep)
    session.flush()
    return ep


def _make_benchmark(session, prompts=None):
    from app.services import crud
    prompts = prompts or [
        {"stable_id": "p1", "title": "P1", "grading_mode": "deterministic",
         "grader_config": {"type": "exact", "canonical_answer": "yes"}, "importance_weight": 1.0,
         "messages": [{"role": "user", "content": "say yes"}]},
        {"stable_id": "p2", "title": "P2", "grading_mode": "deterministic",
         "grader_config": {"type": "exact", "canonical_answer": "no"}, "importance_weight": 1.0,
         "messages": [{"role": "user", "content": "say no"}]},
    ]
    bench = crud.create_benchmark_set(session, {"name": "T", "prompts": prompts})
    return bench


async def _fake_target_chat(base_url, **kw):
    return ChatResult(
        content="yes", finish_reason="stop", truncated=False,
        usage={"total_tokens": 10}, http_status=200,
        time_to_first_token=0.1, total_response_time=0.5, retry_count=0,
        raw={"streamed": True},
    )


@pytest.mark.asyncio
async def test_reasoning_effort_reaches_chat_completion_extra_body(temp_data_dir, monkeypatch):
    """Run-level reasoning_effort must be merged into chat_template_kwargs."""
    captured: dict = {"extra_body": None}
    async def fake_chat(base_url, **kw):
        captured["extra_body"] = kw.get("extra_body")
        return ChatResult(
            content="yes", finish_reason="stop", truncated=False,
            usage={"total_tokens": 10}, http_status=200,
            time_to_first_token=0.1, total_response_time=0.5, retry_count=0,
            raw={"streamed": True},
        )
    monkeypatch.setattr(engine, "chat_completion", fake_chat)
    from app.models import EndpointProfile as EP
    profile = EP(
        id=str(uuid.uuid4()), name="t", base_url="http://x/v1", default_model="m",
        request_timeout=30.0, verify_tls=True, custom_headers={},
        extra_body_params={}, enabled=True, has_api_key=False,
        api_key_storage="none", api_key_env_var="",
    )
    await engine._execute_target_prompt(
        "run-1", profile, "m", None, {"max_tokens": 0},
        {"max_tokens": 0, "reasoning_effort": "xhigh"},
        {"stable_id": "p", "messages": [{"role": "user", "content": "hi"}],
         "generation_overrides": {}},
    )
    assert captured["extra_body"] == {"chat_template_kwargs": {"reasoning_effort": "xhigh"}}


@pytest.mark.asyncio
async def test_reasoning_effort_in_prompt_override_wins(temp_data_dir, monkeypatch):
    """A per-prompt generation_overrides.reasoning_effort beats the run config."""
    captured: dict = {"extra_body": None}
    async def fake_chat(base_url, **kw):
        captured["extra_body"] = kw.get("extra_body")
        return ChatResult(
            content="yes", finish_reason="stop", truncated=False,
            usage={"total_tokens": 10}, http_status=200,
            time_to_first_token=0.1, total_response_time=0.5, retry_count=0,
            raw={"streamed": True},
        )
    monkeypatch.setattr(engine, "chat_completion", fake_chat)
    from app.models import EndpointProfile as EP
    profile = EP(
        id=str(uuid.uuid4()), name="t", base_url="http://x/v1", default_model="m",
        request_timeout=30.0, verify_tls=True, custom_headers={},
        extra_body_params={}, enabled=True, has_api_key=False,
        api_key_storage="none", api_key_env_var="",
    )
    await engine._execute_target_prompt(
        "run-1", profile, "m", None, {}, {"max_tokens": 0, "reasoning_effort": "low"},
        {"stable_id": "p", "messages": [{"role": "user", "content": "hi"}],
         "generation_overrides": {"reasoning_effort": "high"}},
    )
    assert captured["extra_body"] == {"chat_template_kwargs": {"reasoning_effort": "high"}}



@pytest.mark.asyncio
async def test_cancel_aborts_in_flight_request_immediately(temp_data_dir):
    """A cancel requested during a slow request must abort it, not wait for it."""
    from app.jobs.engine import _await_abortable, JobCancelled, clear_cancel, signal_cancel

    started = asyncio.Event()
    released = asyncio.Event()

    async def slow_request():
        started.set()
        await released.wait()  # never released before abort -> hangs if not cancelled
        return "done"

    async def do_cancel():
        await started.wait()
        signal_cancel("run-cancel-test")
        return None

    cancel_task = asyncio.create_task(do_cancel())
    try:
        await _await_abortable(slow_request(), "run-cancel-test")
    except JobCancelled:
        pass
    else:
        raise AssertionError("expected JobCancelled from aborted in-flight request")
    finally:
        clear_cancel("run-cancel-test")
        released.set()
        await cancel_task


def test_update_progress_counts_generation_complete_during_target_phase(session):
    """Progress must advance once generation stored a response, before grading."""
    from app.jobs.engine import create_run_executions, _update_progress
    from app.models import BenchmarkRun, BenchmarkSet, TargetResponse
    bench = _make_benchmark(session)
    run = BenchmarkRun(
        id=str(uuid.uuid4()), name="r", status=RunStatus.RUNNING_TARGET.value,
        benchmark_id=bench.id, benchmark_snapshot={},
        target_endpoint_id=None, target_endpoint_name="", target_model="m",
        target_settings={}, judge_settings={}, run_config={},
    )
    session.add(run)
    session.flush()
    snapshot = {
        "prompts": [
            {"stable_id": "p1", "enabled": True, "messages": [], "grading_mode": "deterministic",
             "grader_config": {"type": "exact", "canonical_answer": "yes"}, "importance_weight": 1.0},
            {"stable_id": "p2", "enabled": True, "messages": [], "grading_mode": "deterministic",
             "grader_config": {"type": "exact", "canonical_answer": "no"}, "importance_weight": 1.0},
        ]
    }
    create_run_executions(session, run, snapshot, 1, False)
    session.flush()
    execs = session.query(PromptExecution).filter(PromptExecution.run_id == run.id).all()
    # One execution has generated (TargetResponse stored) but not been graded.
    session.add(TargetResponse(id=str(uuid.uuid4()), execution_id=execs[0].id, content="yes"))
    session.flush()
    _update_progress(session, run.id)
    assert run.completed_prompts == 1


def test_executions_created_in_order(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {
        "benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo",
        "run_config": {"repetitions": 2},
    })
    session.flush()
    execs = session.query(PromptExecution).filter(PromptExecution.run_id == run.id).order_by(PromptExecution.position).all()
    assert len(execs) == 4  # 2 prompts x 2 reps
    assert run.total_prompts == 4
    positions = [e.position for e in execs]
    assert positions == [0, 1, 2, 3]


def test_mark_interrupted_on_startup(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.RUNNING_TARGET.value
    session.commit()
    count = mark_interrupted_active_runs(session)
    assert count == 1
    session.expire_all()
    assert session.get(BenchmarkRun, run.id).status == RunStatus.INTERRUPTED.value


def test_mark_interrupted_leaves_terminal_runs(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.COMPLETED.value
    session.flush()
    count = mark_interrupted_active_runs(session)
    assert count == 0


def test_resume_run_resets_running_to_pending(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.INTERRUPTED.value
    # Mark one execution as running (in-flight when interrupted).
    execs = session.query(PromptExecution).filter(PromptExecution.run_id == run.id).all()
    execs[0].status = PromptStatus.RUNNING.value
    session.commit()
    ok = resume_run(run.id)
    assert ok is True
    session.expire_all()
    refreshed = session.get(PromptExecution, execs[0].id)
    assert refreshed.status == PromptStatus.PENDING.value
    run2 = session.get(BenchmarkRun, run.id)
    assert run2.status == RunStatus.QUEUED.value


def test_resume_only_interrupted_runs(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.COMPLETED.value
    session.flush()
    assert resume_run(run.id) is False


def test_cancel_request_marks_cancel_requested(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.RUNNING_TARGET.value
    session.commit()
    assert request_cancel(run.id) is True
    session.expire_all()
    assert session.get(BenchmarkRun, run.id).status == RunStatus.CANCEL_REQUESTED.value


def test_cancel_refuses_terminal_run(session):
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    run.status = RunStatus.COMPLETED.value
    session.flush()
    assert request_cancel(run.id) is False


def test_completed_prompt_preserved_after_interrupt(session):
    """A completed prompt must not be rerun on resume."""
    bench = _make_benchmark(session)
    ep = _make_endpoint(session)
    run = crud.create_run(session, {"benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo"})
    execs = session.query(PromptExecution).filter(PromptExecution.run_id == run.id).all()
    execs[0].status = PromptStatus.COMPLETED.value
    execs[0].final_score = 100.0
    run.status = RunStatus.INTERRUPTED.value
    session.commit()
    ok = resume_run(run.id)
    assert ok is True
    session.expire_all()
    done = session.get(PromptExecution, execs[0].id)
    # Still completed with its score intact.
    assert done.status == PromptStatus.COMPLETED.value
    assert done.final_score == 100.0


@pytest.mark.asyncio
async def test_full_run_deterministic_only(temp_data_dir, monkeypatch):
    """End-to-end run with mocked target; deterministic-only."""
    monkeypatch.setattr(engine, "chat_completion", _fake_target_chat)
    with session_scope() as session:
        bench = _make_benchmark(session)
        ep = _make_endpoint(session)
        run = crud.create_run(session, {
            "benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo",
            "run_config": {"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        })
        run_id = run.id
        ep_obj = EndpointProfile(
            id=ep.id, name=ep.name, base_url=ep.base_url, default_model=ep.default_model,
            request_timeout=ep.request_timeout, verify_tls=ep.verify_tls,
            custom_headers=ep.custom_headers, extra_body_params=ep.extra_body_params,
            enabled=True, has_api_key=False, api_key_storage="none", api_key_env_var="",
        )
    await engine.run_job(
        run_id, target_profile=ep_obj, target_model="demo", target_session_key=None,
        target_settings={}, judge_profile=None, judge_model="", judge_session_key=None,
        judge_settings={}, run_config={"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        judge_enabled=False, verifier_enabled=False,
    )
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run.status in {RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_ERRORS.value}
        # p1 (canonical yes) matches -> 100; p2 (canonical no) gets "yes" -> 0
        execs = session.query(PromptExecution).filter(PromptExecution.run_id == run_id).order_by(PromptExecution.position).all()
        scores = [e.final_score for e in execs]
        assert scores == [100.0, 0.0]
        assert run.summary["scoring_coverage"] == "2 of 2 prompts"


def _detached(ep):
    """A plain, session-independent copy usable after the scope closes."""
    return EndpointProfile(
        id=ep.id, name=ep.name, base_url=ep.base_url, default_model=ep.default_model,
        request_timeout=ep.request_timeout, verify_tls=ep.verify_tls,
        custom_headers=dict(ep.custom_headers or {}),
        extra_body_params=dict(ep.extra_body_params or {}),
        enabled=True, has_api_key=False, api_key_storage="none", api_key_env_var="",
    )


@pytest.mark.asyncio
async def test_judge_invalid_output_is_repaired_with_candidate(temp_data_dir, monkeypatch):
    """A judge that first returns invalid JSON gets one repair attempt.

    Regression: the repair request must re-send the *actual* candidate answer
    (it previously sent an empty string, so the judge re-graded nothing) and go
    to the real judge endpoint.
    """
    captured: dict = {"judge_calls": 0, "repair_messages": None}
    valid_judge = json.dumps({
        "dimension_scores": {"c": {"score": 30, "maximum": 40, "reason": "ok"}},
        "raw_total": 30, "critical_error": False, "score_cap": None,
        "final_score": 75, "confidence": 0.9, "strengths": [], "deductions": [],
    })

    async def fake_chat(base_url=None, **kw):
        messages = kw.get("messages", [])
        is_judge = any(
            "impartial evaluator" in (m.get("content") or "")
            for m in messages if m.get("role") == "system"
        )
        if not is_judge:  # target call
            return ChatResult(
                content="CANDIDATE-ANSWER-42", finish_reason="stop", truncated=False,
                usage={"total_tokens": 5}, http_status=200, time_to_first_token=0.1,
                total_response_time=0.2, retry_count=0, raw={},
            )
        captured["judge_calls"] += 1
        if captured["judge_calls"] == 1:  # first judge reply: unparseable
            body = "totally not json"
        else:  # repair reply: valid
            captured["repair_messages"] = messages
            body = valid_judge
        return ChatResult(
            content=body, finish_reason="stop", truncated=False, usage={},
            http_status=200, time_to_first_token=None, total_response_time=0.2,
            retry_count=0, raw={},
        )

    monkeypatch.setattr(engine, "chat_completion", fake_chat)
    with session_scope() as session:
        prompts = [
            {"stable_id": "j1", "title": "J1", "grading_mode": "judge",
             "grader_config": {"reference_answer": "x",
                               "rubric_dimensions": [{"name": "c", "weight": 1, "maximum": 100}]},
             "messages": [{"role": "user", "content": "q"}]},
        ]
        bench = _make_benchmark(session, prompts=prompts)
        target = _make_endpoint(session, name="Target")
        judge = _make_endpoint(session, name="Judge")
        run = crud.create_run(session, {
            "benchmark_id": bench.id, "target_endpoint_id": target.id, "target_model": "demo",
            "judge_endpoint_id": judge.id, "judge_model": "judge-model",
            "run_config": {"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        })
        run_id = run.id
        target_obj, judge_obj = _detached(target), _detached(judge)

    await engine.run_job(
        run_id, target_profile=target_obj, target_model="demo", target_session_key=None,
        target_settings={}, judge_profile=judge_obj, judge_model="judge-model",
        judge_session_key=None, judge_settings={"temperature": 0.0, "max_tokens": 2048},
        run_config={"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        judge_enabled=True, verifier_enabled=False,
    )

    with session_scope() as session:
        e = session.query(PromptExecution).filter(PromptExecution.run_id == run_id).first()
        assert e.status == PromptStatus.COMPLETED.value
        assert e.final_score == 75.0  # repaired judgment applied
    assert captured["judge_calls"] == 2  # one bad, one repair
    assert captured["repair_messages"] is not None
    assert any(
        "CANDIDATE-ANSWER-42" in (m.get("content") or "")
        for m in captured["repair_messages"]
    ), "repair request must include the real candidate answer"


@pytest.mark.asyncio
async def test_judge_required_without_judge_defers(temp_data_dir, monkeypatch):
    """Judge-required prompts run target but defer judging."""
    monkeypatch.setattr(engine, "chat_completion", _fake_target_chat)
    with session_scope() as session:
        prompts = [
            {"stable_id": "j1", "title": "J1", "grading_mode": "judge",
             "grader_config": {"reference_answer": "x", "rubric_dimensions": [{"name": "c", "weight": 1, "maximum": 100}]},
             "messages": [{"role": "user", "content": "q"}]},
        ]
        bench = _make_benchmark(session, prompts=prompts)
        ep = _make_endpoint(session)
        run = crud.create_run(session, {
            "benchmark_id": bench.id, "target_endpoint_id": ep.id, "target_model": "demo",
            "run_config": {"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        })
        run_id = run.id
        ep_obj = EndpointProfile(
            id=ep.id, name=ep.name, base_url=ep.base_url, default_model=ep.default_model,
            request_timeout=ep.request_timeout, verify_tls=ep.verify_tls,
            custom_headers=ep.custom_headers, extra_body_params=ep.extra_body_params,
            enabled=True, has_api_key=False, api_key_storage="none", api_key_env_var="",
        )
    await engine.run_job(
        run_id, target_profile=ep_obj, target_model="demo", target_session_key=None,
        target_settings={}, judge_profile=None, judge_model="", judge_session_key=None,
        judge_settings={}, run_config={"repetitions": 1, "streaming_enabled": True, "timeout": 30},
        judge_enabled=False, verifier_enabled=False,
    )
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run.status == RunStatus.COMPLETED.value
        e = session.query(PromptExecution).filter(PromptExecution.run_id == run_id).first()
        assert e.status == PromptStatus.AWAITING_JUDGE.value
        assert e.final_score is None
