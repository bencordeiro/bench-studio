"""Pydantic schemas for runs, executions, and results."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel
from app.schemas.prompts import GenerationOverrides


# --------------------------------------------------------------------------- #
# Run creation and configuration
# --------------------------------------------------------------------------- #
class RunConfig(ORMModel):
    repetitions: int = Field(default=1, ge=1, le=20)
    sequential_execution: bool = True
    shuffle_prompt_order: bool = False
    warm_up_request: bool = False
    streaming_enabled: bool = True
    judge_verification_enabled: bool = False
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 0
    reasoning_effort: str | None = None
    timeout: float = 60.0
    retry_max_attempts: int = 3
    retry_backoff_base: float = 0.5
    retry_backoff_max: float = 30.0


class RunCreateRequest(ORMModel):
    name: str = ""
    notes: str = ""
    benchmark_id: str
    target_endpoint_id: str
    target_model: str = ""
    target_session_key: str | None = Field(default=None, exclude=True)
    target_settings: GenerationOverrides = Field(default_factory=GenerationOverrides)
    judge_endpoint_id: str | None = None
    judge_model: str = ""
    judge_temperature: float = 0.0
    judge_max_tokens: int = 2048
    judge_session_key: str | None = Field(default=None, exclude=True)
    verifier_enabled: bool = False
    run_config: RunConfig = Field(default_factory=RunConfig)
    auto_start: bool = True

    @model_validator(mode="after")
    def _check(self):
        if not self.target_endpoint_id:
            raise ValueError("target_endpoint_id is required")
        if not self.benchmark_id:
            raise ValueError("benchmark_id is required")
        return self


class RunResponse(ORMModel):
    id: str
    name: str
    notes: str
    status: str
    benchmark_id: str
    target_endpoint_id: str | None
    target_endpoint_name: str
    target_model: str
    judge_endpoint_id: str | None
    judge_endpoint_name: str
    judge_model: str
    judge_enabled: bool
    verifier_enabled: bool
    run_config: dict
    summary: dict
    error_message: str
    total_prompts: int
    completed_prompts: int
    failed_prompts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @property
    def is_terminal(self) -> bool:  # pragma: no cover - trivial helper
        return self.status in {
            "completed",
            "completed_with_errors",
            "cancelled",
            "failed",
        }


class RunSummary(ORMModel):
    id: str
    name: str
    status: str
    target_model: str
    target_endpoint_name: str
    benchmark_name: str | None
    total_prompts: int
    completed_prompts: int
    failed_prompts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    quality_score: float | None = None
    reliability_score: float | None = None
    performance_index: float | None = None
    composite_score: float | None = None
    total_cost: float | None = None


# --------------------------------------------------------------------------- #
# Live progress events (SSE)
# --------------------------------------------------------------------------- #
class ProgressEvent(ORMModel):
    event: str
    run_id: str
    status: str | None = None
    phase: str | None = None
    current_prompt: str | None = None
    completed: int | None = None
    total: int | None = None
    progress: float | None = None
    elapsed_seconds: float | None = None
    eta_seconds: float | None = None
    last_score: float | None = None
    error_count: int | None = None
    message: str | None = None
    timestamp: str | None = None


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
class PerformanceMetricResponse(ORMModel):
    time_to_first_token: float | None
    total_response_time: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    tokens_estimated: bool
    output_tokens_per_second: float | None
    finish_reason: str
    http_status: int | None
    retry_count: int
    truncated: bool
    response_char_count: int
    cost: float | None = None


class ExecutionDetail(ORMModel):
    id: str
    run_id: str
    prompt_snapshot_id: str
    position: int
    repetition: int
    status: str
    final_score: float | None
    max_score: float
    error_message: str
    title: str
    category: str
    grading_mode: str
    importance_weight: float
    messages: list[dict]
    candidate_response: str
    reference_answer: str
    finish_reason: str
    timing: dict
    deterministics: list[dict]
    judge: dict | None
    verifier: dict | None
    manual: dict | None
    raw_meta: dict


class RunResults(ORMModel):
    run: RunResponse
    summary: dict
    executions: list[ExecutionDetail]
    charts: dict
    coverage: dict


class ComparisonResponse(ORMModel):
    run_ids: list[str]
    runs: list[dict]
    per_prompt: list[dict]
    warnings: list[str]


class LeaderboardSuiteSummary(BaseModel):
    """A benchmark suite eligible for leaderboard display."""
    suite_id: str
    suite_name: str
    suite_version: str
    run_count: int = 0
    model_count: int = 0
    top_model: str | None = None
    top_quality_score: float | None = None
    last_run_at: str | None = None


class LeaderboardEntry(BaseModel):
    """One ranked model row in a leaderboard."""
    rank: int
    model: str
    run_count: int
    run_ids: list[str]
    # The run the ranking reflects: for basis=best, the run that produced the
    # max of the sort metric; otherwise the most recent run. Deep-compare links
    # use this so the compared run matches the scores shown in the table.
    representative_run_id: str
    target_endpoint_names: list[str]
    quality_score: float | None
    reliability_score: float | None
    performance_index: float | None
    composite_score: float | None
    last_run_at: str | None = None


class LeaderboardResponse(BaseModel):
    suite_id: str
    suite_name: str
    suite_version: str
    scoring_basis: str  # best | mean | latest
    sort_metric: str    # quality | performance | composite | reliability
    total_runs: int
    entries: list[LeaderboardEntry]
    warnings: list[str]


class ManualGradeRequest(ORMModel):
    score: float = Field(..., ge=0, le=100)
    notes: str = ""
    dimension_scores: dict = Field(default_factory=dict)
