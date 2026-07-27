"""Versioned benchmark-set import/export (JSON).

Format is documented in BENCHMARK_FORMAT.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.models import BenchmarkPrompt, BenchmarkSet, PromptMessage

FORMAT_VERSION = "1.0"


class ExportMessage(BaseModel):
    role: str
    content: str
    position: int = 0


class ExportPrompt(BaseModel):
    stable_id: str = ""
    title: str = ""
    description: str = ""
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    importance_weight: float = 1.0
    position: int = 0
    enabled: bool = True
    grading_mode: str = "deterministic"
    generation_overrides: dict = Field(default_factory=dict)
    grader_config: dict = Field(default_factory=dict)
    messages: list[ExportMessage] = Field(default_factory=list)


class BenchmarkExport(BaseModel):
    format: str = "localbench-benchmark"
    format_version: str = FORMAT_VERSION
    exported_at: str = ""
    name: str
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    scoring_config: dict = Field(default_factory=dict)
    performance_thresholds: dict = Field(default_factory=dict)
    composite_weights: dict = Field(default_factory=dict)
    prompts: list[ExportPrompt] = Field(default_factory=list)


def serialize_benchmark(bench: BenchmarkSet, prompts: list[BenchmarkPrompt],
                       messages_by_prompt: dict[str, list[PromptMessage]]) -> dict[str, Any]:
    export_prompts = []
    for p in sorted(prompts, key=lambda x: x.position):
        msgs = messages_by_prompt.get(p.id, [])
        export_prompts.append(
            ExportPrompt(
                stable_id=p.stable_id,
                title=p.title,
                description=p.description,
                category=p.category,
                tags=p.tags or [],
                difficulty=p.difficulty,
                importance_weight=p.importance_weight,
                position=p.position,
                enabled=p.enabled,
                grading_mode=p.grading_mode,
                generation_overrides=p.generation_overrides or {},
                grader_config=p.grader_config or {},
                messages=[
                    ExportMessage(role=m.role, content=m.content, position=m.position)
                    for m in sorted(msgs, key=lambda x: x.position)
                ],
            )
        )
    return BenchmarkExport(
        exported_at=datetime.now(timezone.utc).isoformat(),
        name=bench.name,
        description=bench.description,
        version=bench.version,
        tags=bench.tags or [],
        scoring_config=bench.scoring_config or {},
        performance_thresholds=bench.performance_thresholds or {},
        composite_weights=bench.composite_weights or {},
        prompts=export_prompts,
    ).model_dump()


class ImportResult(BaseModel):
    success: bool
    benchmark_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    prompts_imported: int = 0


def parse_benchmark_export(data: dict[str, Any]) -> tuple[BenchmarkExport | None, list[str]]:
    try:
        return BenchmarkExport.model_validate(data), []
    except ValidationError as e:
        return None, [f"Validation error: {e}"]


def build_models_from_export(export: BenchmarkExport) -> tuple[BenchmarkSet, list[BenchmarkPrompt]]:
    bench_id = str(uuid.uuid4())
    bench = BenchmarkSet(
        id=bench_id,
        name=export.name,
        description=export.description,
        version=export.version,
        tags=export.tags,
        scoring_config=export.scoring_config,
        performance_thresholds=export.performance_thresholds,
        composite_weights=export.composite_weights,
        is_example=False,
    )
    prompts: list[BenchmarkPrompt] = []
    for ep in export.prompts:
        p = BenchmarkPrompt(
            id=str(uuid.uuid4()),
            benchmark_id=bench_id,
            stable_id=ep.stable_id,
            title=ep.title,
            description=ep.description,
            category=ep.category,
            tags=ep.tags,
            difficulty=ep.difficulty,
            importance_weight=ep.importance_weight,
            position=ep.position,
            enabled=ep.enabled,
            grading_mode=ep.grading_mode,
            generation_overrides=ep.generation_overrides,
            grader_config=ep.grader_config,
            messages=[
                PromptMessage(id=str(uuid.uuid4()), role=m.role, content=m.content, position=m.position)
                for m in ep.messages
            ],
        )
        prompts.append(p)
    return bench, prompts
