"""Snapshot construction: immutable copies of benchmark/endpoint config for a run."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import BenchmarkPrompt, BenchmarkSet, EndpointProfile, PromptMessage


def snapshot_endpoint(profile: EndpointProfile, include_connection: bool = True) -> dict[str, Any]:
    """Endpoint settings excluding all secrets."""
    return {
        "id": profile.id,
        "name": profile.name,
        "base_url": profile.base_url,
        "default_model": profile.default_model,
        "request_timeout": profile.request_timeout,
        "verify_tls": profile.verify_tls,
        "custom_headers": profile.custom_headers or {},
        "extra_body_params": profile.extra_body_params or {},
        "has_api_key": profile.has_api_key,
        "api_key_storage": profile.api_key_storage,
        "api_key_env_var": profile.api_key_env_var,
        "input_price_per_1m": profile.input_price_per_1m,
        "output_price_per_1m": profile.output_price_per_1m,
        # No key value is ever snapshotted.
    }


def snapshot_message(msg: PromptMessage) -> dict[str, Any]:
    return {"role": msg.role, "content": msg.content, "position": msg.position}


def snapshot_prompt(prompt: BenchmarkPrompt, messages: list[PromptMessage]) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "stable_id": prompt.stable_id,
        "title": prompt.title,
        "description": prompt.description,
        "category": prompt.category,
        "tags": prompt.tags or [],
        "difficulty": prompt.difficulty,
        "importance_weight": prompt.importance_weight,
        "position": prompt.position,
        "enabled": prompt.enabled,
        "grading_mode": prompt.grading_mode,
        "generation_overrides": prompt.generation_overrides or {},
        "grader_config": prompt.grader_config or {},
        "messages": [
            {"role": m.role, "content": m.content, "position": m.position}
            for m in sorted(messages, key=lambda x: x.position)
        ],
    }


def snapshot_benchmark(
    session: Session, benchmark: BenchmarkSet
) -> dict[str, Any]:
    prompts = (
        session.query(BenchmarkPrompt)
        .filter(BenchmarkPrompt.benchmark_id == benchmark.id)
        .order_by(BenchmarkPrompt.position)
        .all()
    )
    prompt_snaps = []
    for p in prompts:
        msgs = (
            session.query(PromptMessage)
            .filter(PromptMessage.prompt_id == p.id)
            .order_by(PromptMessage.position)
            .all()
        )
        prompt_snaps.append(snapshot_prompt(p, msgs))
    return {
        "id": benchmark.id,
        "name": benchmark.name,
        "description": benchmark.description,
        "version": benchmark.version,
        "tags": benchmark.tags or [],
        "scoring_config": benchmark.scoring_config or {},
        "performance_thresholds": benchmark.performance_thresholds or {},
        "composite_weights": benchmark.composite_weights or {},
        "prompts": prompt_snaps,
    }
