"""Equal-weight aggregate quality ranking across the user's chosen suites."""
from __future__ import annotations

import math
from statistics import fmean

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.leaderboards import (
    _aggregate,
    _fetch_run_rows,
    _metric,
    _round,
    _run_time,
    _runs_by_model,
    _to_iso,
    _version_warnings,
)
from app.db.session import get_db
from app.models import BenchmarkSet
from app.services.index_config import index_config

router = APIRouter(prefix="/api/index", tags=["index"])


def _fully_scored(row) -> bool:
    value = _metric(row, "quality_score")
    if value is None or not math.isfinite(value) or not 0 <= value <= 100:
        return False
    summary = row.summary or {}
    scored, total = summary.get("scored_count"), summary.get("total_count")
    # Legacy summaries may not record coverage. Explicitly partial grading must
    # not produce a full-suite Index score; generation failures remain graded 0.
    return scored is None or total is None or (
        isinstance(total, int) and not isinstance(total, bool) and total > 0 and scored == total
    )


@router.get("/config", response_model=dict)
def get_index_config(session: Session = Depends(get_db)):
    return index_config(session)


@router.get("", response_model=dict)
def get_index(basis: str = Query("latest"), session: Session = Depends(get_db)):
    if basis not in {"latest", "best", "mean"}:
        raise HTTPException(status_code=400, detail="Invalid scoring basis")
    config = index_config(session)
    choices = config["suites"]
    ids = [s["id"] for s in choices if not s["missing"]]
    rows_by_suite = _fetch_run_rows(session, ids)
    models = sorted({r.target_model or "(unknown)" for rows in rows_by_suite.values() for r in rows})
    entries = {model: {"model": model, "suite_scores": [], "run_count": 0, "last_run_at": None,
                       "target_endpoint_names": [], "_scores": []} for model in models}
    last_times = {}
    warnings = []
    for choice in choices:
        rows = rows_by_suite.get(choice["id"], [])
        if choice["missing"]:
            warnings.append(f"{choice['name']} is missing. It still counts toward required coverage; edit Index settings.")
        else:
            suite = session.get(BenchmarkSet, choice["id"])
            warnings.extend(f"{suite.name}: {w}" for w in _version_warnings(rows, suite))
        grouped = _runs_by_model(rows)
        if any(not _fully_scored(r) for r in rows):
            warnings.append(f"{choice['name']}: runs with missing quality or incomplete grading are excluded.")
        for model, entry in entries.items():
            eligible = [r for r in grouped.get(model, []) if _fully_scored(r)]
            ordered = sorted(eligible, key=lambda r: (_run_time(r), r.id), reverse=True)
            score = _aggregate(ordered, "quality_score", basis) if ordered else None
            if score is not None:
                entry["_scores"].append(score)
            representative = (max(ordered, key=lambda r: _metric(r, "quality_score"))
                              if ordered and basis == "best" else ordered[0] if ordered else None)
            entry["suite_scores"].append({"suite_id": choice["id"], "score": _round(score),
                                          "run_count": len(ordered),
                                          "representative_run_id": representative.id if representative else None})
            entry["run_count"] += len(ordered)
            for r in ordered:
                if r.target_endpoint_name and r.target_endpoint_name not in entry["target_endpoint_names"]:
                    entry["target_endpoint_names"].append(r.target_endpoint_name)
                if model not in last_times or _run_time(r) > last_times[model]:
                    last_times[model] = _run_time(r)
            if model in last_times:
                entry["last_run_at"] = _to_iso(last_times[model])
    for entry in entries.values():
        scores = entry.pop("_scores")
        entry["completed_suites"] = len(scores)
        entry["required_suites"] = len(choices)
        entry["index_score"] = _round(fmean(scores)) if choices and len(scores) == len(choices) else None
        entry["rank"] = None
    complete = [entry for entry in entries.values() if entry["index_score"] is not None]
    ranked = sorted(complete, key=lambda e: (-(e["index_score"] or 0), e["model"].lower()))
    for rank, entry in enumerate(ranked, 1):
        entry["rank"] = rank
    return {**config, "scoring_basis": basis, "entries": ranked, "warnings": warnings,
            "incomplete_model_count": len(entries) - len(complete)}
