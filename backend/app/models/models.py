"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.enums import (
    DeterministicGraderType,
    GradingMode,
    PromptStatus,
    RunStatus,
    SecretStorageMethod,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Endpoint profiles
# --------------------------------------------------------------------------- #
class EndpointProfile(Base):
    __tablename__ = "endpoint_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    default_model: Mapped[str] = mapped_column(String(500), default="")
    request_timeout: Mapped[float] = mapped_column(Float, default=60.0)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extra_body_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    # Credentials are never persisted here in plaintext. These flags describe
    # how a key is *resolved*, not the key itself.
    has_api_key: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_storage: Mapped[str] = mapped_column(String(40), default=SecretStorageMethod.NONE.value)
    api_key_env_var: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    __table_args__ = (Index("ix_endpoint_profiles_name", "name"),)


# --------------------------------------------------------------------------- #
# Benchmark sets and prompts
# --------------------------------------------------------------------------- #
class BenchmarkSet(Base):
    __tablename__ = "benchmark_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    performance_thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    composite_weights: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False)
    show_in_leaderboards: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    prompts: Mapped[list["BenchmarkPrompt"]] = relationship(
        back_populates="benchmark",
        cascade="all, delete-orphan",
        order_by="BenchmarkPrompt.position",
    )

    __table_args__ = (Index("ix_benchmark_sets_name", "name"),)


class BenchmarkPrompt(Base):
    __tablename__ = "benchmark_prompts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    benchmark_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("benchmark_sets.id", ondelete="CASCADE"), nullable=False
    )
    stable_id: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(400), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(200), default="general")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(50), default="medium")
    importance_weight: Mapped[float] = mapped_column(Float, default=1.0)
    position: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    grading_mode: Mapped[str] = mapped_column(String(30), default=GradingMode.DETERMINISTIC.value)
    generation_overrides: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    grader_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    benchmark: Mapped[BenchmarkSet] = relationship(back_populates="prompts")
    messages: Mapped[list["PromptMessage"]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
        order_by="PromptMessage.position",
    )

    __table_args__ = (
        Index("ix_benchmark_prompts_benchmark", "benchmark_id"),
        Index("ix_benchmark_prompts_category", "category"),
    )


class PromptMessage(Base):
    __tablename__ = "prompt_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("benchmark_prompts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)

    prompt: Mapped[BenchmarkPrompt] = relationship(back_populates="messages")


# --------------------------------------------------------------------------- #
# Runs and executions (immutable snapshots preserve history)
# --------------------------------------------------------------------------- #
class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default=RunStatus.QUEUED.value)
    benchmark_id: Mapped[str] = mapped_column(String(36), nullable=False)
    benchmark_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    target_endpoint_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_endpoint_name: Mapped[str] = mapped_column(String(200), default="")
    target_model: Mapped[str] = mapped_column(String(500), default="")
    target_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    judge_endpoint_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    judge_endpoint_name: Mapped[str] = mapped_column(String(200), default="")
    judge_model: Mapped[str] = mapped_column(String(500), default="")
    judge_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    judge_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    verifier_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    run_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str] = mapped_column(Text, default="")

    total_prompts: Mapped[int] = mapped_column(Integer, default=0)
    completed_prompts: Mapped[int] = mapped_column(Integer, default=0)
    failed_prompts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    executions: Mapped[list["PromptExecution"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_runs_status", "status"),
        Index("ix_runs_created", "created_at"),
        Index("ix_runs_model", "target_model"),
        Index("ix_runs_benchmark", "benchmark_id"),
    )


class PromptExecution(Base):
    __tablename__ = "prompt_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False
    )
    prompt_snapshot_id: Mapped[str] = mapped_column(String(200), default="")
    repetition: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default=PromptStatus.PENDING.value)
    prompt_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    weighted: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[BenchmarkRun] = relationship(back_populates="executions")
    target_response: Mapped[list["TargetResponse"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    deterministic_grades: Mapped[list["DeterministicGrade"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    judge_grade: Mapped[list["JudgeGrade"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    verifier_grade: Mapped[list["VerifierGrade"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    manual_grade: Mapped[list["ManualGrade"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    performance_metrics: Mapped[list["PerformanceMetric"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_executions_run", "run_id"),
        Index("ix_executions_status", "status"),
        Index("ix_executions_position", "position"),
        Index("ix_executions_score", "final_score"),
    )


class TargetResponse(Base):
    __tablename__ = "target_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, default="")
    finish_reason: Mapped[str] = mapped_column(String(60), default="")
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    execution: Mapped[PromptExecution] = relationship(back_populates="target_response")


class DeterministicGrade(Base):
    __tablename__ = "deterministic_grades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    grader_type: Mapped[str] = mapped_column(String(40), default=DeterministicGraderType.EXACT.value)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    execution: Mapped[PromptExecution] = relationship(back_populates="deterministic_grades")


class JudgeGrade(Base):
    __tablename__ = "judge_grades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    raw_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_error: Mapped[bool] = mapped_column(Boolean, default=False)
    score_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    deductions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw_response: Mapped[str] = mapped_column(Text, default="")
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    repair_attempted: Mapped[bool] = mapped_column(Boolean, default=False)

    execution: Mapped[PromptExecution] = relationship(back_populates="judge_grade")


class VerifierGrade(Base):
    __tablename__ = "verifier_grades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    original_score: Mapped[float] = mapped_column(Float, default=0.0)
    verified_score: Mapped[float] = mapped_column(Float, default=0.0)
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    adjustment_reason: Mapped[str] = mapped_column(Text, default="")
    problems_found: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_response: Mapped[str] = mapped_column(Text, default="")
    valid: Mapped[bool] = mapped_column(Boolean, default=True)

    execution: Mapped[PromptExecution] = relationship(back_populates="verifier_grade")


class ManualGrade(Base):
    __tablename__ = "manual_grades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str] = mapped_column(Text, default="")
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    graded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    execution: Mapped[PromptExecution] = relationship(back_populates="manual_grade")


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False
    )
    request_start: Mapped[str] = mapped_column(String(40), default="")
    time_to_first_token: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_response_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    output_tokens_per_second: Mapped[float | None] = mapped_column(Float, nullable=True)
    finish_reason: Mapped[str] = mapped_column(String(60), default="")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    response_char_count: Mapped[int] = mapped_column(Integer, default=0)

    execution: Mapped[PromptExecution] = relationship(back_populates="performance_metrics")


class ApplicationSetting(Base):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


__all__ = [
    "ApplicationSetting",
    "BenchmarkPrompt",
    "BenchmarkRun",
    "BenchmarkSet",
    "DeterministicGrade",
    "EndpointProfile",
    "JudgeGrade",
    "ManualGrade",
    "PerformanceMetric",
    "PromptExecution",
    "PromptMessage",
    "TargetResponse",
    "VerifierGrade",
    "DeterministicGraderType",
    "GradingMode",
    "PromptStatus",
    "RunStatus",
    "SecretStorageMethod",
]
