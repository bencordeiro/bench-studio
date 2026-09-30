"""Pydantic schemas for application settings and diagnostics."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

DEFAULT_COMPOSITE_WEIGHTS = {"quality": 0.85, "reliability": 0.10, "performance": 0.05}
DEFAULT_INDEX_SUITE_NAMES = (
    "Code Reasoning & Correctness (Python)",
    "Mini Master",
    "Instruction-Following & Format Adherence",
    "Cyber",
    "Terminal Semantics & System Gotchas",
    "Agentic Tool-Use & Structured Output (Hermes)",
    "Web Dev Correctness & Debugging (JS)",
)


class AppSettings(BaseModel):
    local_data_path: str = ""
    log_level: str = "INFO"
    default_timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    default_retry_max_attempts: int = 3
    default_retry_backoff_base: float = 0.5
    default_retry_backoff_max: float = 30.0
    default_temperature: float = 0.0
    default_top_p: float = 1.0
    default_max_tokens: int = Field(default=0, ge=0)
    # None follows the seven curated defaults; [] explicitly disables the Index.
    index_suite_ids: list[str] | None = Field(default=None, max_length=50)
    composite_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_COMPOSITE_WEIGHTS))
    automatic_backup: bool = True
    launch_browser: bool = True
    theme: str = "dark"
    allow_plaintext_key_fallback: bool = False
    keyring_available: bool = True

    @field_validator("index_suite_ids")
    @classmethod
    def _unique_index_suites(cls, value):
        if value is not None and (len(set(value)) != len(value) or any(not sid for sid in value)):
            raise ValueError("Index suites must be unique, nonempty benchmark IDs")
        return value


class DiagnosticsReport(BaseModel):
    application_version: str
    python_version: str
    platform: str
    db_path: str
    data_dir: str
    frontend_version: str
    frontend_built: bool
    keyring_available: bool
    recent_errors: list[str] = Field(default_factory=list)
    endpoint_profile_names: list[str] = Field(default_factory=list)
