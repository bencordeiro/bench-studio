"""Resolve saved Index membership without silently dropping missing suites."""
from sqlalchemy.orm import Session

from app.models import ApplicationSetting, BenchmarkSet
from app.schemas.settings import DEFAULT_INDEX_SUITE_NAMES


def index_config(session: Session) -> dict:
    suites = session.query(BenchmarkSet).order_by(BenchmarkSet.created_at, BenchmarkSet.id).all()
    by_id = {s.id: s for s in suites}
    by_name = {}
    for suite in suites:
        by_name.setdefault(suite.name, suite)
    defaults = [by_name.get(name) for name in DEFAULT_INDEX_SUITE_NAMES]
    row = session.get(ApplicationSetting, "app")
    selected_ids = (row.value or {}).get("index_suite_ids") if row else None
    if selected_ids is None:
        choices = [(s, name) for s, name in zip(defaults, DEFAULT_INDEX_SUITE_NAMES, strict=True)]
    else:
        choices = [(by_id.get(sid), f"Missing benchmark ({sid})") for sid in selected_ids]
    return {
        "uses_defaults": selected_ids is None,
        "default_suite_ids": [s.id for s in defaults if s],
        "suites": [{"id": s.id if s else (selected_ids[i] if selected_ids is not None else None),
                    "name": s.name if s else name, "version": s.version if s else None,
                    "missing": s is None} for i, (s, name) in enumerate(choices)],
    }
