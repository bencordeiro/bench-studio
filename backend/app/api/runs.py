"""Runs: creation, control, live progress (SSE), results, comparison."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_execution_or_404, get_run_or_404
from app.db.session import get_db
from app.exports.run_export import _collect_run, export_csv, export_html, export_json
from app.jobs.engine import compute_run_summary
from app.jobs.event_bus import bus
from app.jobs.runner import enqueue_run, request_cancel, resume_run, runner
from app.models import (
    BenchmarkRun,
    DeterministicGrade,
    JudgeGrade,
    ManualGrade,
    PerformanceMetric,
    PromptExecution,
    RunStatus,
    TargetResponse,
    VerifierGrade,
)
from app.models.enums import COMPLETED_STATUSES
from app.schemas import (
    ManualGradeRequest,
    RunCreateRequest,
    RunResponse,
    RunResults,
    RunSummary,
)
from app.services import crud

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_to_response(run: BenchmarkRun, session: Session) -> RunResponse:
    return RunResponse(
        id=run.id,
        name=run.name,
        notes=run.notes,
        status=run.status,
        benchmark_id=run.benchmark_id,
        target_endpoint_id=run.target_endpoint_id,
        target_endpoint_name=run.target_endpoint_name,
        target_model=run.target_model,
        judge_endpoint_id=run.judge_endpoint_id,
        judge_endpoint_name=run.judge_endpoint_name,
        judge_model=run.judge_model,
        judge_enabled=run.judge_enabled,
        verifier_enabled=run.verifier_enabled,
        run_config=run.run_config or {},
        summary=run.summary or {},
        error_message=run.error_message,
        total_prompts=run.total_prompts,
        completed_prompts=run.completed_prompts,
        failed_prompts=run.failed_prompts,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _summary(run: BenchmarkRun) -> RunSummary:
    s = run.summary or {}
    bench_name = (run.benchmark_snapshot or {}).get("name", "")
    return RunSummary(
        id=run.id,
        name=run.name,
        status=run.status,
        target_model=run.target_model,
        target_endpoint_name=run.target_endpoint_name,
        benchmark_name=bench_name,
        total_prompts=run.total_prompts,
        completed_prompts=run.completed_prompts,
        failed_prompts=run.failed_prompts,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        quality_score=s.get("quality_score"),
        reliability_score=s.get("reliability_score"),
        performance_index=s.get("performance_index"),
        composite_score=s.get("composite_score"),
    )


@router.get("", response_model=list[RunSummary])
def list_runs(limit: int = Query(50, le=200), offset: int = 0, session: Session = Depends(get_db)):
    rows = session.execute(
        select(BenchmarkRun)
        .order_by(BenchmarkRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return [_summary(r) for r in rows]


@router.post("", response_model=RunResponse, status_code=201)
def create_run(payload: RunCreateRequest, session: Session = Depends(get_db)):
    try:
        run = crud.create_run(session, payload.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    session.commit()
    if payload.auto_start:
        enqueue_run(run.id)
    return _run_to_response(run, session)


# --------------------------------------------------------------------------- #
# Comparison (declared before /{run_id} so the static path is not swallowed)
# --------------------------------------------------------------------------- #
@router.get("/compare", response_model=dict)
def compare_runs(ids: list[str] = Query(default=[]), session: Session = Depends(get_db)):
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least two run ids")
    runs = []
    warnings = []
    per_prompt: dict[str, dict] = {}
    for rid in ids:
        run = session.get(BenchmarkRun, rid)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {rid} not found")
        s = run.summary or {}
        runs.append({
            "id": run.id,
            "name": run.name,
            "target_model": run.target_model,
            "target_endpoint_name": run.target_endpoint_name,
            "judge_model": run.judge_model,
            "quality_score": s.get("quality_score"),
            "reliability_score": s.get("reliability_score"),
            "performance_index": s.get("performance_index"),
            "composite_score": s.get("composite_score"),
            "benchmark_version": (run.benchmark_snapshot or {}).get("version"),
            "benchmark_name": (run.benchmark_snapshot or {}).get("name"),
        })
        execs = (
            session.query(PromptExecution)
            .filter(PromptExecution.run_id == run.id)
            .order_by(PromptExecution.position)
            .all()
        )
        for e in execs:
            key = e.prompt_snapshot_id or e.id
            per_prompt.setdefault(key, {"label": (e.prompt_snapshot or {}).get("title", key), "scores": {}})["scores"][run.id] = e.final_score
    # Warnings when configurations differ.
    versions = {r["benchmark_version"] for r in runs if r["benchmark_version"]}
    if len(versions) > 1:
        warnings.append("Runs use different benchmark versions; comparability is limited.")
    judges = {r["judge_model"] for r in runs if r["judge_model"]}
    if len(judges) > 1:
        warnings.append("Runs used different judge models; judge scores may not be directly comparable.")
    per_prompt_list = [{"key": k, **v} for k, v in per_prompt.items()]
    return {"run_ids": ids, "runs": runs, "per_prompt": per_prompt_list, "warnings": warnings}


@router.get("/{run_id}", response_model=RunResponse)
def get_run(run_id: str, session: Session = Depends(get_db)):
    return _run_to_response(get_run_or_404(session, run_id), session)


# Terminal states a run may be deleted from (in-flight runs must be cancelled first).
DELETABLE_STATUSES = frozenset({
    RunStatus.COMPLETED.value,
    RunStatus.COMPLETED_WITH_ERRORS.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.INTERRUPTED.value,
})


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, session: Session = Depends(get_db)):
    """Delete a run and all of its executions/grades/metrics (cascades).

    Refuses an in-flight run — cancel it first so the background job cannot
    write to rows that are being removed.
    """
    run = get_run_or_404(session, run_id)
    if run.id == runner.current_run_id or run.status not in DELETABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="This run is still active. Cancel it before deleting.",
        )
    session.delete(run)  # relationships cascade to executions, grades, metrics
    session.commit()


@router.post("/clear-failed", response_model=dict)
def clear_failed_runs(session: Session = Depends(get_db)):
    """Delete every fully-failed run (status == failed). Returns the count removed."""
    runs = (
        session.query(BenchmarkRun)
        .filter(BenchmarkRun.status == RunStatus.FAILED.value)
        .all()
    )
    deleted = 0
    for run in runs:
        if run.id == runner.current_run_id:
            continue
        session.delete(run)
        deleted += 1
    session.commit()
    return {"deleted": deleted}


# --------------------------------------------------------------------------- #
# Control
# --------------------------------------------------------------------------- #
@router.post("/{run_id}/start", response_model=RunResponse)
def start_run(run_id: str, session: Session = Depends(get_db)):
    run = get_run_or_404(session, run_id)
    if run.status not in {"queued", "interrupted", "preparing"}:
        raise HTTPException(status_code=400, detail=f"Cannot start run in status '{run.status}'")
    if run.status == "interrupted":
        ok = resume_run(run.id)
        if not ok:
            raise HTTPException(status_code=400, detail="Run could not be resumed")
    else:
        run.status = "queued"
        session.commit()
        enqueue_run(run.id)
    return _run_to_response(get_run_or_404(session, run_id), session)


@router.post("/{run_id}/cancel", response_model=RunResponse)
def cancel_run(run_id: str, session: Session = Depends(get_db)):
    if not request_cancel(run_id):
        raise HTTPException(status_code=400, detail="Run cannot be cancelled in its current state")
    return _run_to_response(get_run_or_404(session, run_id), session)


@router.post("/{run_id}/resume", response_model=RunResponse)
def resume_run_endpoint(run_id: str, session: Session = Depends(get_db)):
    if not resume_run(run_id):
        raise HTTPException(status_code=400, detail="Only interrupted runs can be resumed")
    return _run_to_response(get_run_or_404(session, run_id), session)


# --------------------------------------------------------------------------- #
# Live progress (SSE with polling fallback)
# --------------------------------------------------------------------------- #
@router.get("/{run_id}/progress")
async def run_progress(run_id: str, session: Session = Depends(get_db)):
    get_run_or_404(session, run_id)

    async def event_stream():
        sub = await bus.subscribe(run_id)
        try:
            while True:
                # Poll current run state for keep-alive + terminal detection.
                from app.db.session import session_scope

                with session_scope() as s:
                    run = s.get(BenchmarkRun, run_id)
                    status_now = run.status if run else "unknown"
                    completed = run.completed_prompts if run else 0
                    total = run.total_prompts if run else 0
                snapshot = {
                    "event": "snapshot",
                    "run_id": run_id,
                    "status": status_now,
                    "completed": completed,
                    "total": total,
                    "progress": round(completed / total, 4) if total else 0.0,
                }
                yield f"data: {json.dumps(snapshot)}\n\n"
                # Drain queued events.
                try:
                    for _ in range(50):
                        evt = sub.queue.get_nowait()
                        yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.QueueEmpty:
                    pass
                if status_now in {
                    "completed", "completed_with_errors", "cancelled", "failed"
                }:
                    done = {"event": "done", "run_id": run_id, "status": status_now}
                    yield f"data: {json.dumps(done)}\n\n"
                    return
                await asyncio.sleep(1.0)
        finally:
            await bus.unsubscribe(run_id, sub)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def _load_related(session: Session, exec_ids: list[str]) -> dict[str, dict]:
    """Fetch every child row for a set of executions in one query per table.

    Building these per-execution meant six queries per prompt; a 28-prompt run
    issued ~170 round trips to render one results page.
    """
    if not exec_ids:
        return {}
    related: dict[str, dict] = {
        eid: {"target": None, "metric": None, "dets": [], "judge": None,
              "verifier": None, "manual": None}
        for eid in exec_ids
    }
    single = [
        (TargetResponse, "target"),
        (PerformanceMetric, "metric"),
        (JudgeGrade, "judge"),
        (VerifierGrade, "verifier"),
        (ManualGrade, "manual"),
    ]
    for model, key in single:
        for row in session.query(model).filter(model.execution_id.in_(exec_ids)).all():
            bucket = related.get(row.execution_id)
            # First row wins, matching the previous .first() semantics.
            if bucket is not None and bucket[key] is None:
                bucket[key] = row
    for row in session.query(DeterministicGrade).filter(
        DeterministicGrade.execution_id.in_(exec_ids)
    ).all():
        bucket = related.get(row.execution_id)
        if bucket is not None:
            bucket["dets"].append(row)
    return related


def _build_execution_detail(e: PromptExecution, related: dict):
    target = related["target"]
    metric = related["metric"]
    dets = related["dets"]
    judge = related["judge"]
    verifier = related["verifier"]
    manual = related["manual"]
    snap = e.prompt_snapshot or {}
    target_raw = (target.raw if target else None) or {}
    timing = {
        "time_to_first_token": metric.time_to_first_token if metric else None,
        "total_response_time": metric.total_response_time if metric else None,
        "output_tokens_per_second": metric.output_tokens_per_second if metric else None,
        "completion_tokens": metric.completion_tokens if metric else None,
        "prompt_tokens": metric.prompt_tokens if metric else None,
        "truncated": metric.truncated if metric else False,
        # "server" means the backend reported its own generation rate, which
        # excludes prefill and network; "computed" is tokens/wall-time.
        "tps_source": target_raw.get("tps_source", "computed"),
        "prompt_tokens_per_second": target_raw.get("prompt_tokens_per_second"),
    }
    return {
        "id": e.id,
        "run_id": e.run_id,
        "prompt_snapshot_id": e.prompt_snapshot_id,
        "position": e.position,
        "repetition": e.repetition,
        "status": e.status,
        "final_score": e.final_score,
        "max_score": e.max_score,
        "error_message": e.error_message,
        "title": snap.get("title", ""),
        "category": snap.get("category", "general"),
        "grading_mode": snap.get("grading_mode", ""),
        "importance_weight": snap.get("importance_weight", 1.0),
        "messages": snap.get("messages", []),
        "candidate_response": target.content if target else "",
        "reference_answer": (snap.get("grader_config", {}) or {}).get("reference_answer", ""),
        "finish_reason": metric.finish_reason if metric else "",
        "timing": timing,
        "deterministics": [
            {"type": d.grader_type, "passed": d.passed, "score": d.score,
             "max_score": d.max_score, "details": d.details}
            for d in dets
        ],
        "judge": _judge_view(judge),
        "verifier": _verifier_view(verifier),
        "manual": _manual_view(manual),
        "raw_meta": {"http_status": metric.http_status if metric else None,
                     "retry_count": metric.retry_count if metric else 0,
                     "tokens_estimated": metric.tokens_estimated if metric else False},
    }


def _judge_view(j):
    if not j:
        return None
    return {
        "final_score": j.final_score, "raw_total": j.raw_total,
        "critical_error": j.critical_error, "score_cap": j.score_cap,
        "confidence": j.confidence, "dimension_scores": j.dimension_scores,
        "strengths": j.strengths, "deductions": j.deductions, "valid": j.valid,
    }


def _verifier_view(v):
    if not v:
        return None
    return {
        "original_score": v.original_score, "verified_score": v.verified_score,
        "adjusted": v.adjusted, "confidence": v.confidence,
        "adjustment_reason": v.adjustment_reason, "problems_found": v.problems_found,
        "valid": v.valid,
    }


def _manual_view(m):
    if not m:
        return None
    return {"score": m.score, "notes": m.notes, "dimension_scores": m.dimension_scores}


def _build_charts(execs_details: list[dict], run: BenchmarkRun) -> dict:
    by_cat: dict[str, list[tuple[float, float]]] = {}
    scores = []
    ttfts = []
    tps_vals = []
    totals = []
    det_vs_judge = {"deterministic": [], "judge": []}
    latency_scatter = []
    for e in execs_details:
        cat = e["category"]
        if e["final_score"] is not None:
            by_cat.setdefault(cat, []).append((e["final_score"], e["importance_weight"]))
            scores.append(e["final_score"])
        t = e["timing"]
        if t.get("time_to_first_token") is not None:
            ttfts.append(t["time_to_first_token"])
        if t.get("output_tokens_per_second") is not None:
            tps_vals.append(t["output_tokens_per_second"])
        if t.get("total_response_time") is not None:
            totals.append(t["total_response_time"])
        if e["final_score"] is not None and t.get("total_response_time") is not None:
            latency_scatter.append({"x": t["total_response_time"], "y": e["final_score"]})
        if e["grading_mode"] in {"deterministic", "execution"} and e["final_score"] is not None:
            det_vs_judge["deterministic"].append(e["final_score"])
        elif e["grading_mode"] in {"judge", "hybrid"} and e["final_score"] is not None:
            det_vs_judge["judge"].append(e["final_score"])
    from app.graders.scoring import category_quality_score

    cat_scores = {c: category_quality_score(v) for c, v in by_cat.items()}
    return {
        "score_by_category": {k: round(v, 2) for k, v in cat_scores.items() if v is not None},
        "score_distribution": scores,
        "prompt_scores": [
            {"label": e["title"][:24] or f"#{e['position']}", "score": e["final_score"]}
            for e in execs_details if e["final_score"] is not None
        ],
        "ttft_distribution": ttfts,
        "output_speed_distribution": tps_vals,
        "total_time_distribution": totals,
        "deterministic_vs_judge": det_vs_judge,
        "score_vs_latency": latency_scatter,
        "repetition_consistency": (run.summary or {}).get("repetition", {}),
    }


@router.get("/{run_id}/results", response_model=RunResults)
def get_results(run_id: str, session: Session = Depends(get_db)):
    run = get_run_or_404(session, run_id)
    execs = (
        session.query(PromptExecution)
        .filter(PromptExecution.run_id == run_id)
        .order_by(PromptExecution.position)
        .all()
    )
    related = _load_related(session, [e.id for e in execs])
    details = [_build_execution_detail(e, related[e.id]) for e in execs]
    # Recompute summary live so manual grades are reflected.
    summary = compute_run_summary(run_id) if run.status in COMPLETED_STATUSES else (run.summary or {})
    if run.status in COMPLETED_STATUSES and summary:
        run.summary = summary
        session.commit()
    coverage = {
        "scored": summary.get("scored_count", 0),
        "total": summary.get("total_count", run.total_prompts),
        "label": summary.get("scoring_coverage", ""),
    }
    return RunResults(
        run=_run_to_response(run, session),
        summary=summary or {},
        executions=details,
        charts=_build_charts(details, run),
        coverage=coverage,
    )


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
@router.get("/{run_id}/export/{fmt}")
def export_run(run_id: str, fmt: str, session: Session = Depends(get_db)):
    from fastapi.responses import Response

    if fmt not in {"json", "csv", "html"}:
        raise HTTPException(status_code=400, detail="format must be json, csv, or html")
    run = get_run_or_404(session, run_id)
    document = _collect_run(session, run)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (run.name or "run"))[:60]
    if fmt == "json":
        return Response(
            content=export_json(document),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
        )
    if fmt == "csv":
        return Response(
            content=export_csv(document),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
        )
    return Response(
        content=export_html(document),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.html"'},
    )


# --------------------------------------------------------------------------- #
# Manual grading
# --------------------------------------------------------------------------- #
@router.post("/executions/{execution_id}/manual", response_model=dict)
def add_manual_grade(execution_id: str, payload: ManualGradeRequest, session: Session = Depends(get_db)):
    execution = get_execution_or_404(session, execution_id)
    grade = crud.add_manual_grade(
        session, execution_id, payload.score, payload.notes, payload.dimension_scores
    )
    session.commit()
    # Persist the recomputed summary so consumers that read run.summary directly
    # (leaderboards, exports) reflect the grade without requiring a results view.
    run = session.get(BenchmarkRun, execution.run_id)
    if run is not None and run.status in COMPLETED_STATUSES:
        summary = compute_run_summary(run.id)
        if summary:
            run.summary = summary
            session.commit()
    return {"execution_id": execution_id, "score": grade.score}

