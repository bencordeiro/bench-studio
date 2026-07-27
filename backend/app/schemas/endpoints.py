"""Pydantic schemas for endpoint profiles."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.urls import normalize_base_url
from app.schemas.common import ORMModel, TimestampMixin


class EndpointProfileBase(ORMModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_url: str = Field(default="", max_length=2000)
    default_model: str = ""
    request_timeout: float = Field(default=60.0, gt=0)
    verify_tls: bool = True
    custom_headers: dict[str, str] = Field(default_factory=dict)
    extra_body_params: dict = Field(default_factory=dict)
    enabled: bool = True
    notes: str = ""
    # The plaintext key is write-only: accepted on create/update, and excluded
    # from responses by EndpointProfileResponse below. It must NOT be excluded
    # here, or model_dump() would drop it before it ever reaches storage.
    api_key: str | None = None
    has_api_key: bool = False
    api_key_storage: str = "none"
    api_key_env_var: str = ""

    @field_validator("base_url")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_base_url(v)

    @field_validator("api_key_env_var")
    @classmethod
    def _env_var(cls, v: str) -> str:
        if v and (not v.isidentifier()):
            raise ValueError("api_key_env_var must be a valid environment variable name")
        return v


class EndpointProfileCreate(EndpointProfileBase):
    pass


class EndpointProfileUpdate(EndpointProfileBase):
    pass


class EndpointProfileResponse(EndpointProfileBase, TimestampMixin):
    id: str
    masked_api_key: str | None = None
    # Never leak the plaintext key in a response (only masked_api_key is shown).
    api_key: str | None = Field(default=None, exclude=True)
    # Masked representation for display, e.g. ••••••••
    @property
    def display_api_key(self) -> str:  # pragma: no cover - trivial
        return self.masked_api_key or ("" if not self.has_api_key else "••••••••")


class ConnectionTestRequest(BaseModel):
    pass


class ConnectionTestResult(BaseModel):
    reachable: bool
    http_status: int | None
    response_time_ms: float | None
    models_discovered: bool
    model_count: int = 0
    models: list[str] = Field(default_factory=list)
    # Whether a real one-token completion was attempted, and its outcome.
    completion_checked: bool = False
    completion_ok: bool = False
    completion_model: str | None = None
    error: str | None = None
    sanitized: bool = True


class FetchModelsResult(BaseModel):
    success: bool
    models: list[str] = Field(default_factory=list)
    error: str | None = None


class SetSessionKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
