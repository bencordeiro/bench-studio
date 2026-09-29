"""Run results export: JSON, CSV summary, standalone HTML report."""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from html import escape
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import sanitize
from app.models import (
    BenchmarkRun,
    DeterministicGrade,
    JudgeGrade,
    ManualGrade,
    PerformanceMetric,
    PromptExecution,
    TargetResponse,
    VerifierGrade,
)

log = logging.getLogger(__name__)


def _collect_run(session: Session, run: BenchmarkRun) -> dict[str, Any]:
    """Assemble a complete, secret-free run document."""
    execs = (
        session.query(PromptExecution)
        .filter(PromptExecution.run_id == run.id)
        .order_by(PromptExecution.position)
        .all()
    )
    prompt_rows = []
    for e in execs:
        target = (
            session.query(TargetResponse)
            .filter(TargetResponse.execution_id == e.id)
            .first()
        )
        metric = (
            session.query(PerformanceMetric)
            .filter(PerformanceMetric.execution_id == e.id)
            .first()
        )
        det = (
            session.query(DeterministicGrade)
            .filter(DeterministicGrade.execution_id == e.id)
            .all()
        )
        judge = (
            session.query(JudgeGrade)
            .filter(JudgeGrade.execution_id == e.id)
            .first()
        )
        verifier = (
            session.query(VerifierGrade)
            .filter(VerifierGrade.execution_id == e.id)
            .first()
        )
        manual = (
            session.query(ManualGrade)
            .filter(ManualGrade.execution_id == e.id)
            .first()
        )
        snap = e.prompt_snapshot or {}
        prompt_rows.append({
            "position": e.position,
            "repetition": e.repetition,
            "stable_id": e.prompt_snapshot_id,
            "title": snap.get("title", ""),
            "category": snap.get("category", "general"),
            "grading_mode": snap.get("grading_mode", ""),
            "weight": snap.get("importance_weight", 1.0),
            "status": e.status,
            "score": e.final_score,
            "max_score": e.max_score,
            "error": e.error_message,
            "messages": snap.get("messages", []),
            "candidate_response": target.content if target else "",
            "reasoning_response": (target.raw or {}).get("reasoning", "") if target else "",
            "generation_diagnostics": (target.raw or {}).get("generation_diagnostics", {}) if target else {},
            "finish_reason": metric.finish_reason if metric else "",
            "timing": {
                "time_to_first_token": metric.time_to_first_token if metric else None,
                "total_response_time": metric.total_response_time if metric else None,
                "output_tokens_per_second": metric.output_tokens_per_second if metric else None,
                "prompt_tokens": metric.prompt_tokens if metric else None,
                "completion_tokens": metric.completion_tokens if metric else None,
                "total_tokens": metric.total_tokens if metric else None,
                "tokens_estimated": metric.tokens_estimated if metric else False,
                "truncated": metric.truncated if metric else False,
                "http_status": metric.http_status if metric else None,
                "retry_count": metric.retry_count if metric else 0,
                "cost": metric.cost if metric else None,
            },
            "deterministic": [
                {"type": d.grader_type, "passed": d.passed, "score": d.score,
                 "max_score": d.max_score, "details": d.details}
                for d in det
            ],
            "judge": _judge_dict(judge),
            "verifier": _verifier_dict(verifier),
            "manual": _manual_dict(manual),
        })
    return sanitize({
        "run": {
            "id": run.id,
            "name": run.name,
            "notes": run.notes,
            "status": run.status,
            "error_message": run.error_message,
            "text_tool_compatibility": (run.benchmark_snapshot or {}).get("text_tool_compatibility", {}),
            "benchmark_name": (run.benchmark_snapshot or {}).get("name", ""),
            "benchmark_version": (run.benchmark_snapshot or {}).get("version", ""),
            "target_endpoint_name": run.target_endpoint_name,
            "target_model": run.target_model,
            "judge_endpoint_name": run.judge_endpoint_name,
            "judge_model": run.judge_model,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "total_prompts": run.total_prompts,
            "completed_prompts": run.completed_prompts,
            "failed_prompts": run.failed_prompts,
        },
        "summary": run.summary or {},
        "prompts": prompt_rows,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    })


def _judge_dict(j: JudgeGrade | None) -> dict | None:
    if j is None:
        return None
    return {
        "final_score": j.final_score,
        "raw_total": j.raw_total,
        "critical_error": j.critical_error,
        "score_cap": j.score_cap,
        "confidence": j.confidence,
        "dimension_scores": j.dimension_scores,
        "strengths": j.strengths,
        "deductions": j.deductions,
        "valid": j.valid,
    }


def _verifier_dict(v: VerifierGrade | None) -> dict | None:
    if v is None:
        return None
    return {
        "original_score": v.original_score,
        "verified_score": v.verified_score,
        "adjusted": v.adjusted,
        "confidence": v.confidence,
        "adjustment_reason": v.adjustment_reason,
        "problems_found": v.problems_found,
        "valid": v.valid,
    }


def _manual_dict(m: ManualGrade | None) -> dict | None:
    if m is None:
        return None
    return {"score": m.score, "notes": m.notes, "dimension_scores": m.dimension_scores}


def export_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, default=str)


def export_csv(document: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "position", "repetition", "stable_id", "title", "category", "grading_mode",
        "weight", "status", "score", "max_score", "time_to_first_token",
        "output_tokens_per_second", "total_response_time", "finish_reason",
        "truncated", "http_status", "retry_count", "cost", "error",
    ])
    for p in document.get("prompts", []):
        t = p.get("timing", {})
        writer.writerow([
            p.get("position"), p.get("repetition"), p.get("stable_id"), p.get("title"),
            p.get("category"), p.get("grading_mode"), p.get("weight"), p.get("status"),
            p.get("score"), p.get("max_score"), t.get("time_to_first_token"),
            t.get("output_tokens_per_second"), t.get("total_response_time"),
            t.get("finish_reason") or p.get("finish_reason"), t.get("truncated"),
            t.get("http_status"), t.get("retry_count"), t.get("cost"), p.get("error"),
        ])
    return out.getvalue()


def export_html(document: dict[str, Any]) -> str:
    run = document.get("run", {})
    summary = document.get("summary", {})
    prompts = document.get("prompts", [])
    rows_html = []
    for p in prompts:
        t = p.get("timing", {}) or {}
        rows_html.append(
            "<tr>"
            f"<td>{escape(str(p.get('position')))}</td>"
            f"<td>{escape(str(p.get('title')))}</td>"
            f"<td>{escape(str(p.get('category')))}</td>"
            f"<td>{escape(str(p.get('grading_mode')))}</td>"
            f"<td>{escape(str(p.get('score')))}</td>"
            f"<td>{escape(str(p.get('status')))}</td>"
            f"<td>{_fmt(t.get('time_to_first_token'))}</td>"
            f"<td>{_fmt(t.get('output_tokens_per_second'))}</td>"
            f"<td>{_fmt(t.get('total_response_time'))}</td>"
            f"<td>{_fmt_cost(t.get('cost'))}</td>"
            "</tr>"
        )
    details = []
    for p in prompts:
        candidate = p.get("candidate_response") or ""
        details.append(
            f"<section class='prompt'><h3>{escape(str(p.get('title')))}</h3>"
            f"<p><em>Category:</em> {escape(str(p.get('category')))} • "
            f"<em>Score:</em> {escape(str(p.get('score')))}</p>"
            f"<pre>{escape(candidate[:4000])}</pre>"
            f"</section>"
        )
    return HTML_TEMPLATE.format(
        title=escape(run.get("name", "Run report")),
        target=escape(run.get("target_endpoint_name", "")),
        model=escape(run.get("target_model", "")),
        judge=escape(run.get("judge_model", "")),
        quality=_fmt(summary.get("quality_score")),
        reliability=_fmt(summary.get("reliability_score")),
        performance=_fmt(summary.get("performance_index")),
        composite=_fmt(summary.get("composite_score")),
        cost=_fmt_cost(summary.get("total_cost")),
        coverage=escape(str(summary.get("scoring_coverage", ""))),
        rows="\n".join(rows_html),
        details="\n".join(details),
        exported=escape(str(document.get("exported_at", ""))),
    )


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    return escape(str(v))


def _fmt_cost(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):.6f}"
    except (ValueError, TypeError):
        return "—"


HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — LocalBench Studio Report</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; background:#0f1115; color:#e6e6e6; margin: 2rem auto; max-width: 1100px; }}
  h1,h2,h3 {{ color:#fff; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th,td {{ border:1px solid #2a2e36; padding:.4rem .6rem; text-align:left; font-size:.9rem; }}
  th {{ background:#1a1d24; }}
  .summary {{ display:flex; gap:1rem; flex-wrap:wrap; }}
  .card {{ background:#1a1d24; border:1px solid #2a2e36; padding:1rem 1.5rem; border-radius:.5rem; flex:1; min-width:140px; }}
  .card .v {{ font-size:1.6rem; font-weight:700; }}
  pre {{ background:#161922; border:1px solid #2a2e36; padding:.8rem; overflow:auto; border-radius:.4rem; white-space:pre-wrap; word-wrap:break-word; }}
  section.prompt {{ margin:1.5rem 0; border-top:1px solid #2a2e36; padding-top:1rem; }}
  footer {{ color:#7a7f8a; margin-top:2rem; font-size:.8rem; }}
</style></head><body>
<h1>{title}</h1>
<p><strong>Target:</strong> {target} • <strong>Model:</strong> {model} • <strong>Judge:</strong> {judge}</p>
<h2>Summary</h2>
<div class="summary">
  <div class="card"><div>Quality</div><div class="v">{quality}</div></div>
  <div class="card"><div>Reliability</div><div class="v">{reliability}</div></div>
  <div class="card"><div>Performance</div><div class="v">{performance}</div></div>
  <div class="card"><div>Composite</div><div class="v">{composite}</div></div>
  <div class="card"><div>Total cost</div><div class="v">{cost}</div></div>
</div>
<p>Coverage: {coverage}</p>
<h2>Prompt results</h2>
<table>
  <tr><th>#</th><th>Prompt</th><th>Category</th><th>Mode</th><th>Score</th><th>Status</th><th>TTFT (s)</th><th>Tok/s</th><th>Total (s)</th><th>Cost</th></tr>
  {rows}
</table>
<h2>Candidate answers</h2>
{details}
<footer>Generated by LocalBench Studio • {exported}</footer>
</body></html>
"""
