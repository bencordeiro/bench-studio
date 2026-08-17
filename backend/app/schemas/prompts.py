"""Pydantic schemas for benchmark sets, prompts, and grader configs."""
from __future__ import annotations

from pydantic import Field, model_validator

from app.schemas.common import ORMModel, TimestampMixin


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #
class PromptMessageCreate(ORMModel):
    role: str = "user"
    content: str = ""
    position: int = 0

    @model_validator(mode="after")
    def _check_role(self):
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError("role must be one of: system, user, assistant")
        return self


class PromptMessageResponse(PromptMessageCreate):
    id: str


# --------------------------------------------------------------------------- #
# Deterministic grader configs
# --------------------------------------------------------------------------- #
class ExactMatchConfig(ORMModel):
    type: str = "exact"
    canonical_answer: str = ""
    accepted_aliases: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    trim_whitespace: bool = True
    normalize_punctuation: bool = True
    points: float = 100.0


class NumericResultConfig(ORMModel):
    type: str = "numeric"
    expected_value: float
    absolute_tolerance: float = 0.0
    relative_tolerance: float = 0.0
    required_unit: str = ""
    unit_aliases: list[str] = Field(default_factory=list)
    points: float = 100.0


class RegexCheckConfig(ORMModel):
    type: str = "regex"
    required_patterns: list[str] = Field(default_factory=list)
    optional_patterns: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    case_sensitive: bool = False
    points: float = 100.0


class ConceptConfig(ORMModel):
    type: str = "concept"
    required_concepts: list[str] = Field(default_factory=list)
    optional_concepts: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    points_per_concept: float = 10.0
    cap: float = 100.0


class StructuredJSONConfig(ORMModel):
    type: str = "json"
    require_valid_json: bool = True
    json_schema: dict | None = None
    required_fields: list[str] = Field(default_factory=list)
    expected_field_values: dict[str, object] = Field(default_factory=dict)
    allow_code_fences: bool = True
    points: float = 100.0


class MultipleChoiceConfig(ORMModel):
    type: str = "multiple_choice"
    correct_option: str
    accepted_formats: list[str] = Field(default_factory=list)
    points: float = 100.0


# --------------------------------------------------------------------------- #
# Judge rubric
# --------------------------------------------------------------------------- #
class RubricDimension(ORMModel):
    name: str
    description: str = ""
    weight: float = 1.0
    maximum: float = 100.0


class JudgeRubricConfig(ORMModel):
    reference_answer: str = ""
    reference_facts: list[str] = Field(default_factory=list)
    required_elements: list[str] = Field(default_factory=list)
    rubric_dimensions: list[RubricDimension] = Field(default_factory=list)
    critical_errors: list[str] = Field(default_factory=list)
    score_caps: list[dict] = Field(default_factory=list)
    judge_instructions: str = ""
    strong_example: str = ""
    weak_example: str = ""

    @model_validator(mode="after")
    def _validate_weights(self):
        # Weights need not sum to anything specific, but each must be >= 0.
        for d in self.rubric_dimensions:
            if d.weight < 0:
                raise ValueError(f"rubric dimension {d.name!r} weight must be >= 0")
            if d.maximum <= 0:
                raise ValueError(f"rubric dimension {d.name!r} maximum must be > 0")
        return self


class HybridConfig(ORMModel):
    """Hybrid grading: deterministic checks combined with judge rubric."""

    deterministic_checks: list[dict] = Field(default_factory=list)
    deterministic_weight: float = Field(default=40.0, ge=0, le=100)
    judge_weight: float = Field(default=60.0, ge=0, le=100)
    judge: JudgeRubricConfig = Field(default_factory=JudgeRubricConfig)
    critical_fail_caps: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _weights_total(self):
        total = self.deterministic_weight + self.judge_weight
        if abs(total - 100.0) > 0.01:
            raise ValueError(
                f"deterministic_weight + judge_weight must total 100 (got {total})"
            )
        return self


# --------------------------------------------------------------------------- #
# Generation overrides
# --------------------------------------------------------------------------- #
class GenerationOverrides(ORMModel):
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None


# --------------------------------------------------------------------------- #
# Benchmark prompt
# --------------------------------------------------------------------------- #
class BenchmarkPromptBase(ORMModel):
    stable_id: str = ""
    title: str = ""
    description: str = ""
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    difficulty: str = "medium"
    importance_weight: float = Field(default=1.0, ge=0)
    position: int = 0
    enabled: bool = True
    grading_mode: str = "deterministic"
    generation_overrides: GenerationOverrides = Field(default_factory=GenerationOverrides)
    grader_config: dict = Field(default_factory=dict)
    messages: list[PromptMessageCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_grading_mode(self):
        if self.grading_mode not in {"deterministic", "judge", "hybrid", "manual", "execution"}:
            raise ValueError(
                "grading_mode must be deterministic, judge, hybrid, manual, or execution"
            )
        return self


class BenchmarkPromptCreate(BenchmarkPromptBase):
    pass


class BenchmarkPromptResponse(BenchmarkPromptBase, TimestampMixin):
    id: str
    benchmark_id: str


# --------------------------------------------------------------------------- #
# Benchmark set
# --------------------------------------------------------------------------- #
class BenchmarkSetBase(ORMModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    scoring_config: dict = Field(default_factory=dict)
    performance_thresholds: dict = Field(default_factory=dict)
    composite_weights: dict[str, float] = Field(default_factory=dict)
    is_example: bool = False
    show_in_leaderboards: bool = False


class BenchmarkSetCreate(BenchmarkSetBase):
    prompts: list[BenchmarkPromptCreate] = Field(default_factory=list)


class BenchmarkSetUpdate(BenchmarkSetBase):
    pass


class BenchmarkSetSummary(ORMModel, TimestampMixin):
    id: str
    name: str
    description: str
    version: str
    tags: list[str]
    is_example: bool
    show_in_leaderboards: bool
    prompt_count: int = 0
    enabled_prompt_count: int = 0


class BenchmarkSetResponse(BenchmarkSetBase, TimestampMixin):
    id: str
    prompts: list[BenchmarkPromptResponse] = Field(default_factory=list)
