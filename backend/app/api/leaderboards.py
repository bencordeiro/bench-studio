"""Per-suite leaderboards.

Ranks every tested model on a benchmark suite, grouping runs by ``target_model``.
Scores are read from each run's frozen ``summary`` snapshot — leaderboards never
recompute historical runs, so weight edits on a suite only affect future runs.

Only suites with ``show_in_leaderboards=True`` are surfaced by the picker
(``GET /api/leaderboards``); the detail endpoint serves any existing suite so
deep links keep working even if the flag is later turned off.

Queries project only the columns the leaderboard needs — never the full
``benchmark_snapshot`` blob, which embeds the entire benchmark.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BenchmarkRun, BenchmarkSet
from app.models.enums import COMPLETED_STATUSES
from app.schemas import (
    LeaderboardEntry,
    LeaderboardResponse,
    LeaderboardSuiteSummary,
)

router = APIRouter(prefix="/api/leaderboards", tags=["leaderboards"])

# Public sort metric -> summary key (also the LeaderboardEntry attribute name).
_SORT_KEYS = {
    "quality": "quality_score",
    "reliability": "reliability_score",
    "performance": "performance_index",
    "composite": "composite_score",
}
_VALID_BASES = ("best", "mean", "latest")


def _fetch_run_rows(session: Session, suite_ids: Sequence[str]) -> dict[str, list[Row]]:
    """Eligible run rows per suite, projecting only the needed columns.

    ``json_extract`` pulls the snapshot version without materializing the
    (large) benchmark_snapshot JSON in Python.
    """
    if not suite_ids:
        return {}
    rows = session.execute(
        select(
            BenchmarkRun.id,
            BenchmarkRun.benchmark_id,
            BenchmarkRun.target_model,
            BenchmarkRun.target_endpoint_name,
            BenchmarkRun.summary,
            BenchmarkRun.completed_at,
            BenchmarkRun.created_at,
            func.json_extract(BenchmarkRun.benchmark_snapshot, "$.version").label(
                "snapshot_version"
            ),
        )
        .where(BenchmarkRun.benchmark_id.in_(suite_ids))
        .where(BenchmarkRun.status.in_(COMPLETED_STATUSES))
    ).all()
    by_suite: dict[str, list[Row]] = {sid: [] for sid in suite_ids}
    for row in rows:
        by_suite[row.benchmark_id].append(row)
    return by_suite


def _runs_by_model(rows: list[Row]) -> dict[str, list[Row]]:
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        grouped.setdefault(row.target_model or "(unknown)", []).append(row)
    return grouped


def _run_time(row: Row) -> datetime:
    return row.completed_at or row.created_at


def _metric(row: Row, summary_key: str) -> float | None:
    """A summary metric as a float, or None when absent or non-numeric."""
    v = (row.summary or {}).get(summary_key)
    # bool is an int subclass; a True/False here would be junk data, not a score.
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _aggregate(rows: list[Row], summary_key: str, basis: str) -> float | None:
    """Aggregate one metric across a model's runs for the given basis.

    ``best`` and ``mean`` ignore runs whose metric is missing (e.g. all-manual
    quality). ``latest`` uses the single most-recent run's value, which may be
    None. Returns None when nothing contributed.
    """
    if basis == "latest":
        return _metric(max(rows, key=_run_time), summary_key)
    values = [v for r in rows if (v := _metric(r, summary_key)) is not None]
    if not values:
        return None
    return max(values) if basis == "best" else fmean(values)


def _to_iso(dt: datetime | None) -> str | None:
    """UTC ISO-8601 with an explicit offset (SQLite hands back naive UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _round(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def _version_warnings(rows: list[Row], suite: BenchmarkSet) -> list[str]:
    versions = {r.snapshot_version for r in rows}
    versions.discard(None)
    if len(versions) > 1:
        return [
            "Runs span different benchmark versions; cross-model comparability is limited."
        ]
    if versions and (only := next(iter(versions))) != suite.version:
        return [
            f"All scores come from runs on benchmark version {only}; "
            f"the suite has since changed to version {suite.version}."
        ]
    return []


@router.get("", response_model=list[LeaderboardSuiteSummary])
def list_leaderboard_suites(session: Session = Depends(get_db)):
    """Suites opted into leaderboards, with a run/model count and top model."""
    suites = session.execute(
        select(BenchmarkSet)
        .where(BenchmarkSet.show_in_leaderboards.is_(True))
        .order_by(BenchmarkSet.updated_at.desc())
    ).scalars().all()
    rows_by_suite = _fetch_run_rows(session, [s.id for s in suites])

    out: list[LeaderboardSuiteSummary] = []
    for suite in suites:
        rows = rows_by_suite.get(suite.id, [])
        by_model = _runs_by_model(rows)
        scored = {
            model: q
            for model, model_rows in by_model.items()
            if (q := _aggregate(model_rows, "quality_score", "best")) is not None
        }
        top_model = max(scored, key=scored.__getitem__) if scored else None
        out.append(LeaderboardSuiteSummary(
            suite_id=suite.id,
            suite_name=suite.name,
            suite_version=suite.version,
            run_count=len(rows),
            model_count=len(by_model),
            top_model=top_model,
            top_quality_score=_round(scored.get(top_model)) if top_model else None,
            last_run_at=_to_iso(max((_run_time(r) for r in rows), default=None)),
        ))
    return out


@router.get("/{suite_id}", response_model=LeaderboardResponse)
def get_leaderboard(
    suite_id: str,
    basis: str = Query("best"),
    sort: str = Query("quality"),
    session: Session = Depends(get_db),
):
    if basis not in _VALID_BASES:
        raise HTTPException(status_code=400, detail=f"Invalid basis '{basis}'")
    if sort not in _SORT_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid sort '{sort}'")

    suite = session.get(BenchmarkSet, suite_id)
    if suite is None:
        raise HTTPException(status_code=404, detail="Benchmark suite not found")

    rows = _fetch_run_rows(session, [suite_id]).get(suite_id, [])
    sort_key = _SORT_KEYS[sort]

    ranked: list[dict] = []
    for model, model_rows in _runs_by_model(rows).items():
        ordered = sorted(model_rows, key=_run_time, reverse=True)
        endpoint_names: list[str] = []
        for r in ordered:
            if r.target_endpoint_name and r.target_endpoint_name not in endpoint_names:
                endpoint_names.append(r.target_endpoint_name)
        # The run whose scores the ranking reflects: for "best", the run that
        # produced the max of the sort metric; otherwise the most recent run.
        representative = ordered[0]
        if basis == "best":
            with_metric = [r for r in ordered if _metric(r, sort_key) is not None]
            if with_metric:
                representative = max(with_metric, key=lambda r: _metric(r, sort_key))
        ranked.append({
            "model": model,
            "run_count": len(ordered),
            "run_ids": [r.id for r in ordered],
            "representative_run_id": representative.id,
            "target_endpoint_names": endpoint_names,
            "quality_score": _round(_aggregate(ordered, "quality_score", basis)),
            "reliability_score": _round(_aggregate(ordered, "reliability_score", basis)),
            "performance_index": _round(_aggregate(ordered, "performance_index", basis)),
            "composite_score": _round(_aggregate(ordered, "composite_score", basis)),
            "last_run_at": _to_iso(_run_time(ordered[0])),
        })

    # Descending by metric; None sorts last; model name breaks ties for stability.
    ranked.sort(key=lambda d: (d[sort_key] is None, -(d[sort_key] or 0.0), d["model"].lower()))
    entries = [LeaderboardEntry(rank=i, **d) for i, d in enumerate(ranked, start=1)]

    return LeaderboardResponse(
        suite_id=suite.id,
        suite_name=suite.name,
        suite_version=suite.version,
        scoring_basis=basis,
        sort_metric=sort,
        total_runs=len(rows),
        entries=entries,
        warnings=_version_warnings(rows, suite),
    )
