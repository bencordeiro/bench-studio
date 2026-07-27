"""Pydantic schemas for application settings and diagnostics."""
from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_COMPOSITE_WEIGHTS = {"quality": 0.85, "reliability": 0.10, "performance": 0.05}


class AppSettings(BaseModel):
    local_data_path: str = ""
    log_level: str = "INFO"
    default_timeout: float = 60.0
    default_retry_max_attempts: int = 3
    default_retry_backoff_base: float = 0.5
    default_retry_backoff_max: float = 30.0
    default_temperature: float = 0.0
    default_top_p: float = 1.0
    default_max_tokens: int = 4096
    composite_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_COMPOSITE_WEIGHTS))
    automatic_backup: bool = True
    launch_browser: bool = True
    theme: str = "dark"
    allow_plaintext_key_fallback: bool = False
    keyring_available: bool = True


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
