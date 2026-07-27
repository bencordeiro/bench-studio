"""CRUD service layer used by the API routers."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.secrets import store_api_key
from app.core.urls import normalize_base_url
from app.models import (
    BenchmarkPrompt,
    BenchmarkRun,
    BenchmarkSet,
    EndpointProfile,
    ManualGrade,
    PromptExecution,
    PromptMessage,
    PromptStatus,
    RunStatus,
)
from app.services.snapshots import snapshot_benchmark, snapshot_endpoint

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Endpoint profiles
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now(timezone.utc)


def create_endpoint_profile(session: Session, data: dict[str, Any]) -> EndpointProfile:
    profile = EndpointProfile(
        id=str(uuid.uuid4()),
        name=data["name"],
        base_url=normalize_base_url(data.get("base_url", "")),
        default_model=data.get("default_model", ""),
        request_timeout=float(data.get("request_timeout", 60.0)),
        verify_tls=bool(data.get("verify_tls", True)),
        custom_headers=data.get("custom_headers", {}) or {},
        extra_body_params=data.get("extra_body_params", {}) or {},
        enabled=bool(data.get("enabled", True)),
        notes=data.get("notes", ""),
        api_key_env_var=data.get("api_key_env_var", ""),
        has_api_key=False,
        api_key_storage="none",
    )
    api_key = data.get("api_key")
    if api_key:
        method = store_api_key(profile.id, api_key)
        profile.has_api_key = True
        profile.api_key_storage = method
    session.add(profile)
    session.flush()
    return profile


def update_endpoint_profile(session: Session, profile: EndpointProfile, data: dict[str, Any]) -> EndpointProfile:
    profile.name = data.get("name", profile.name)
    profile.base_url = normalize_base_url(data.get("base_url", profile.base_url))
    profile.default_model = data.get("default_model", profile.default_model)
    profile.request_timeout = float(data.get("request_timeout", profile.request_timeout))
    profile.verify_tls = bool(data.get("verify_tls", profile.verify_tls))
    profile.custom_headers = data.get("custom_headers", profile.custom_headers) or {}
    profile.extra_body_params = data.get("extra_body_params", profile.extra_body_params) or {}
    profile.enabled = bool(data.get("enabled", profile.enabled))
    profile.notes = data.get("notes", profile.notes)
    profile.api_key_env_var = data.get("api_key_env_var", profile.api_key_env_var)
    api_key = data.get("api_key")
    if api_key:
        method = store_api_key(profile.id, api_key)
        profile.has_api_key = True
        profile.api_key_storage = method
    profile.updated_at = _now()
    session.flush()
    return profile


def duplicate_endpoint_profile(session: Session, profile: EndpointProfile) -> EndpointProfile:
    new = EndpointProfile(
        id=str(uuid.uuid4()),
        name=f"{profile.name} (copy)",
        base_url=profile.base_url,
        default_model=profile.default_model,
        request_timeout=profile.request_timeout,
        verify_tls=profile.verify_tls,
        custom_headers=dict(profile.custom_headers or {}),
        extra_body_params=dict(profile.extra_body_params or {}),
        enabled=profile.enabled,
        notes=profile.notes,
        api_key_env_var=profile.api_key_env_var,
        has_api_key=False,
        api_key_storage="none",
    )
    session.add(new)
    session.flush()
    return new


def set_session_key_hint(session: Session, profile: EndpointProfile) -> None:
    """Mark that a session key is in use (no value stored)."""
    if not profile.has_api_key:
        profile.api_key_storage = "session"
        session.flush()


# --------------------------------------------------------------------------- #
# Benchmarks and prompts
# --------------------------------------------------------------------------- #
def create_benchmark_set(session: Session, data: dict[str, Any]) -> BenchmarkSet:
    bench = BenchmarkSet(
        id=str(uuid.uuid4()),
        name=data["name"],
        description=data.get("description", ""),
        version=data.get("version", "1.0.0"),
        tags=data.get("tags", []) or [],
        scoring_config=data.get("scoring_config", {}) or {},
        performance_thresholds=data.get("performance_thresholds", {}) or {},
        composite_weights=data.get("composite_weights", {}) or {},
        is_example=bool(data.get("is_example", False)),
        show_in_leaderboards=bool(data.get("show_in_leaderboards", False)),
    )
    session.add(bench)
    session.flush()
    for i, p in enumerate(data.get("prompts", []) or []):
        _add_prompt(session, bench.id, p, position=p.get("position", i))
    return bench


def _add_prompt(session: Session, bench_id: str, data: dict[str, Any], position: int) -> BenchmarkPrompt:
    prompt = BenchmarkPrompt(
        id=str(uuid.uuid4()),
        benchmark_id=bench_id,
        stable_id=data.get("stable_id", f"prompt-{uuid.uuid4().hex[:8]}"),
        title=data.get("title", ""),
        description=data.get("description", ""),
        category=data.get("category", "general"),
        tags=data.get("tags", []) or [],
        difficulty=data.get("difficulty", "medium"),
        importance_weight=float(data.get("importance_weight", 1.0)),
        position=position,
        enabled=bool(data.get("enabled", True)),
        grading_mode=data.get("grading_mode", "deterministic"),
        generation_overrides=data.get("generation_overrides", {}) or {},
        grader_config=data.get("grader_config", {}) or {},
    )
    session.add(prompt)
    session.flush()
    for i, m in enumerate(data.get("messages", []) or []):
        session.add(PromptMessage(
            id=str(uuid.uuid4()),
            prompt_id=prompt.id,
            role=m.get("role", "user"),
            content=m.get("content", ""),
            position=m.get("position", i),
        ))
    return prompt


def update_benchmark_set(session: Session, bench: BenchmarkSet, data: dict[str, Any]) -> BenchmarkSet:
    bench.name = data.get("name", bench.name)
    bench.description = data.get("description", bench.description)
    bench.version = data.get("version", bench.version)
    bench.tags = data.get("tags", bench.tags) or []
    bench.scoring_config = data.get("scoring_config", bench.scoring_config) or {}
    bench.performance_thresholds = data.get("performance_thresholds", bench.performance_thresholds) or {}
    bench.composite_weights = data.get("composite_weights", bench.composite_weights) or {}
    # Editable boolean flags (previously dropped silently on update).
    if "is_example" in data:
        bench.is_example = bool(data["is_example"])
    if "show_in_leaderboards" in data:
        bench.show_in_leaderboards = bool(data["show_in_leaderboards"])
    bench.updated_at = _now()
    session.flush()
    return bench


def duplicate_benchmark_set(session: Session, bench: BenchmarkSet) -> BenchmarkSet:
    new = BenchmarkSet(
        id=str(uuid.uuid4()),
        name=f"{bench.name} (copy)",
        description=bench.description,
        version=bench.version,
        tags=list(bench.tags or []),
        scoring_config=dict(bench.scoring_config or {}),
        performance_thresholds=dict(bench.performance_thresholds or {}),
        composite_weights=dict(bench.composite_weights or {}),
        is_example=False,
        show_in_leaderboards=False,
    )
    session.add(new)
    session.flush()
    prompts = (
        session.query(BenchmarkPrompt)
        .filter(BenchmarkPrompt.benchmark_id == bench.id)
        .order_by(BenchmarkPrompt.position)
        .all()
    )
    for p in prompts:
        np = BenchmarkPrompt(
            id=str(uuid.uuid4()),
            benchmark_id=new.id,
            stable_id=p.stable_id,
            title=p.title,
            description=p.description,
            category=p.category,
            tags=list(p.tags or []),
            difficulty=p.difficulty,
            importance_weight=p.importance_weight,
            position=p.position,
            enabled=p.enabled,
            grading_mode=p.grading_mode,
            generation_overrides=dict(p.generation_overrides or {}),
            grader_config=dict(p.grader_config or {}),
        )
        session.add(np)
        session.flush()
        msgs = session.query(PromptMessage).filter(PromptMessage.prompt_id == p.id).all()
        for m in msgs:
            session.add(PromptMessage(
                id=str(uuid.uuid4()),
                prompt_id=np.id,
                role=m.role,
                content=m.content,
                position=m.position,
            ))
    return new


def upsert_prompt(session: Session, bench_id: str, prompt_id: str | None, data: dict[str, Any]) -> BenchmarkPrompt:
    if prompt_id:
        prompt = session.get(BenchmarkPrompt, prompt_id)
        if prompt is None:
            raise ValueError("Prompt not found")
    else:
        prompt = BenchmarkPrompt(id=str(uuid.uuid4()), benchmark_id=bench_id, position=999)
        session.add(prompt)
    prompt.stable_id = data.get("stable_id", prompt.stable_id)
    prompt.title = data.get("title", prompt.title)
    prompt.description = data.get("description", prompt.description)
    prompt.category = data.get("category", prompt.category)
    prompt.tags = data.get("tags", prompt.tags) or []
    prompt.difficulty = data.get("difficulty", prompt.difficulty)
    prompt.importance_weight = float(data.get("importance_weight", prompt.importance_weight))
    if "position" in data:
        prompt.position = int(data["position"])
    prompt.enabled = bool(data.get("enabled", prompt.enabled))
    prompt.grading_mode = data.get("grading_mode", prompt.grading_mode)
    prompt.generation_overrides = data.get("generation_overrides", prompt.generation_overrides) or {}
    prompt.grader_config = data.get("grader_config", prompt.grader_config) or {}
    if "messages" in data:
        # Replace messages.
        session.query(PromptMessage).filter(PromptMessage.prompt_id == prompt.id).delete(
            synchronize_session=False
        )
        for i, m in enumerate(data["messages"]):
            session.add(PromptMessage(
                id=str(uuid.uuid4()),
                prompt_id=prompt.id,
                role=m.get("role", "user"),
                content=m.get("content", ""),
                position=m.get("position", i),
            ))
    session.flush()
    return prompt


def reorder_prompts(session: Session, bench_id: str, ordered_ids: list[str]) -> None:
    for i, pid in enumerate(ordered_ids):
        p = session.get(BenchmarkPrompt, pid)
        if p and p.benchmark_id == bench_id:
            p.position = i
    session.flush()


def duplicate_prompt(session: Session, prompt: BenchmarkPrompt) -> BenchmarkPrompt:
    new = BenchmarkPrompt(
        id=str(uuid.uuid4()),
        benchmark_id=prompt.benchmark_id,
        stable_id=prompt.stable_id,
        title=f"{prompt.title} (copy)",
        description=prompt.description,
        category=prompt.category,
        tags=list(prompt.tags or []),
        difficulty=prompt.difficulty,
        importance_weight=prompt.importance_weight,
        position=prompt.position + 1,
        enabled=prompt.enabled,
        grading_mode=prompt.grading_mode,
        generation_overrides=dict(prompt.generation_overrides or {}),
        grader_config=dict(prompt.grader_config or {}),
    )
    session.add(new)
    session.flush()
    msgs = session.query(PromptMessage).filter(PromptMessage.prompt_id == prompt.id).all()
    for m in msgs:
        session.add(PromptMessage(
            id=str(uuid.uuid4()),
            prompt_id=new.id,
            role=m.role,
            content=m.content,
            position=m.position,
        ))
    return new


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def create_run(session: Session, data: dict[str, Any]) -> BenchmarkRun:
    benchmark = session.get(BenchmarkSet, data["benchmark_id"])
    if benchmark is None:
        raise ValueError("Benchmark not found")
    target = session.get(EndpointProfile, data["target_endpoint_id"]) if data.get("target_endpoint_id") else None
    if target is None:
        raise ValueError("Target endpoint not found")
    judge = session.get(EndpointProfile, data["judge_endpoint_id"]) if data.get("judge_endpoint_id") else None
    bench_snapshot = snapshot_benchmark(session, benchmark)
    bench_snapshot["target"] = snapshot_endpoint(target) if target else {}
    bench_snapshot["judge"] = snapshot_endpoint(judge) if judge else {}
    run_config = data.get("run_config", {}) or {}
    enabled_prompts = [p for p in bench_snapshot.get("prompts", []) if p.get("enabled", True)]
    if not enabled_prompts:
        raise ValueError("Benchmark has no enabled prompts")
    # A judge is optional; if judge-required prompts exist but no judge is
    # configured, the target still runs and judging is deferred.
    judge_enabled = bool(data.get("judge_endpoint_id") and data.get("judge_model"))

    run = BenchmarkRun(
        id=str(uuid.uuid4()),
        name=data.get("name") or f"{benchmark.name} — {target.name}",
        notes=data.get("notes", ""),
        status=RunStatus.QUEUED.value,
        benchmark_id=benchmark.id,
        benchmark_snapshot=bench_snapshot,
        target_endpoint_id=target.id,
        target_endpoint_name=target.name,
        target_model=data.get("target_model") or target.default_model or "",
        target_settings=data.get("target_settings", {}) or {},
        judge_endpoint_id=judge.id if judge else None,
        judge_endpoint_name=judge.name if judge else "",
        judge_model=data.get("judge_model") or (judge.default_model if judge else ""),
        judge_settings={
            "temperature": float(data.get("judge_temperature", 0.0)),
            "max_tokens": int(data.get("judge_max_tokens", 2048)),
        },
        judge_enabled=judge_enabled,
        verifier_enabled=bool(data.get("verifier_enabled", False)),
        run_config=run_config,
        summary={},
    )
    session.add(run)
    session.flush()

    # Create executions.
    from app.jobs.engine import create_run_executions

    create_run_executions(
        session, run, bench_snapshot,
        repetitions=int(run_config.get("repetitions", 1)),
        shuffle=bool(run_config.get("shuffle_prompt_order", False)),
    )
    session.flush()
    return run


def add_manual_grade(session: Session, execution_id: str, score: float, notes: str,
                     dimension_scores: dict) -> ManualGrade:
    execution = session.get(PromptExecution, execution_id)
    if execution is None:
        raise ValueError("Execution not found")
    grade = ManualGrade(
        id=str(uuid.uuid4()),
        execution_id=execution_id,
        score=score,
        notes=notes,
        dimension_scores=dimension_scores or {},
    )
    session.add(grade)
    execution.final_score = float(score)
    execution.max_score = 100.0
    if execution.status in {PromptStatus.AWAITING_MANUAL.value, PromptStatus.AWAITING_JUDGE.value}:
        execution.status = PromptStatus.COMPLETED.value
    session.flush()
    return grade
