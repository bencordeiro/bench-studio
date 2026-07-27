"""Shared schema helpers."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


def to_camel(string: str) -> str:
    parts = string.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampMixin(BaseModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    python_version: str
    platform: str
    db_path: str
    data_dir: str
    frontend_built: bool
