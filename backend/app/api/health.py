"""Health, settings, and diagnostics endpoints."""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import APP_VERSION, get_settings
from app.core.secrets import is_keyring_available
from app.db.session import get_db
from app.models import ApplicationSetting, EndpointProfile
from app.schemas import AppSettings, DiagnosticsReport, HealthResponse
from app.schemas.settings import DEFAULT_COMPOSITE_WEIGHTS

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health():
    from pathlib import Path

    settings = get_settings()
    # app/api/health.py -> parents[0]=api, [1]=app, [2]=backend, [3]=repo root
    frontend_dir = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    frontend_built = (frontend_dir / "index.html").exists()
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        db_path=str(settings.db_path),
        data_dir=str(settings.data_dir),
        frontend_built=frontend_built,
    )


def _load_settings(session: Session) -> AppSettings:
    settings = get_settings()
    row = session.get(ApplicationSetting, "app")
    stored = row.value if row else {}
    weights = stored.get("composite_weights", dict(DEFAULT_COMPOSITE_WEIGHTS))
    return AppSettings(
        local_data_path=str(settings.data_dir),
        log_level=stored.get("log_level", settings.log_level),
        default_timeout=stored.get("default_timeout", 60.0),
        default_retry_max_attempts=stored.get("default_retry_max_attempts", 3),
        default_retry_backoff_base=stored.get("default_retry_backoff_base", 0.5),
        default_retry_backoff_max=stored.get("default_retry_backoff_max", 30.0),
        default_temperature=stored.get("default_temperature", 0.0),
        default_top_p=stored.get("default_top_p", 1.0),
        default_max_tokens=stored.get("default_max_tokens", AppSettings().default_max_tokens),
        composite_weights=weights,
        automatic_backup=stored.get("automatic_backup", True),
        launch_browser=stored.get("launch_browser", True),
        theme=stored.get("theme", "dark"),
        allow_plaintext_key_fallback=settings.allow_plaintext_key_fallback,
        keyring_available=is_keyring_available(),
    )


def _save_settings(session: Session, data: AppSettings) -> AppSettings:
    row = session.get(ApplicationSetting, "app")
    value = {
        "log_level": data.log_level,
        "default_timeout": data.default_timeout,
        "default_retry_max_attempts": data.default_retry_max_attempts,
        "default_retry_backoff_base": data.default_retry_backoff_base,
        "default_retry_backoff_max": data.default_retry_backoff_max,
        "default_temperature": data.default_temperature,
        "default_top_p": data.default_top_p,
        "default_max_tokens": data.default_max_tokens,
        "composite_weights": data.composite_weights,
        "automatic_backup": data.automatic_backup,
        "launch_browser": data.launch_browser,
        "theme": data.theme,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if row is None:
        row = ApplicationSetting(key="app", value=value)
    else:
        row.value = value
    session.add(row)
    return data


@router.get("/settings", response_model=AppSettings)
def get_app_settings(session: Session = Depends(get_db)):
    return _load_settings(session)


@router.put("/settings", response_model=AppSettings)
def update_app_settings(payload: AppSettings, session: Session = Depends(get_db)):
    return _save_settings(session, payload)


@router.get("/diagnostics", response_model=DiagnosticsReport)
def diagnostics(session: Session = Depends(get_db)):
    from pathlib import Path

    from app.core.config import APP_VERSION

    settings = get_settings()
    frontend_dir = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    profiles = session.query(EndpointProfile).order_by(EndpointProfile.name).all()
    # Recent errors are not stored as a separate table; pull from failed runs.
    from app.models import BenchmarkRun
    failed = (
        session.query(BenchmarkRun)
        .filter(BenchmarkRun.error_message != "")
        .order_by(BenchmarkRun.created_at.desc())
        .limit(10)
        .all()
    )
    return DiagnosticsReport(
        application_version=APP_VERSION,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        db_path=str(settings.db_path),
        data_dir=str(settings.data_dir),
        frontend_version="1.0.0",
        frontend_built=(frontend_dir / "index.html").exists(),
        keyring_available=is_keyring_available(),
        recent_errors=[(r.error_message or "")[:200] for r in failed if r.error_message],
        endpoint_profile_names=[p.name for p in profiles],
    )
