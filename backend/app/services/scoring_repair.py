"""Repair derived scores from saved responses, without any endpoint requests."""
from __future__ import annotations

from app.db.session import session_scope
from app.graders.scoring import QUALITY_SCORING_VERSION
from app.models import BenchmarkRun, PerformanceMetric, PromptExecution, TargetResponse


def repair_saved_run_scores() -> int:
    # Import lazily: startup has finished loading the engine/API modules.
    from app.jobs.engine import _update_progress, compute_run_summary

    finished = {"completed", "completed_with_errors", "failed", "cancelled"}
    with session_scope() as session:
        run_ids = [rid for rid, summary in session.query(BenchmarkRun.id, BenchmarkRun.summary)
                   .filter(BenchmarkRun.status.in_(finished))
                   .filter(BenchmarkRun.id.in_(session.query(PromptExecution.run_id))).all()
                   if (summary or {}).get("quality_scoring_version") != QUALITY_SCORING_VERSION]
    for run_id in run_ids:
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            executions = session.query(PromptExecution).filter_by(run_id=run_id).all()
            ids = [execution.id for execution in executions]
            capped = {row.execution_id for model in (PerformanceMetric, TargetResponse)
                      for row in session.query(model.execution_id, model.truncated, model.finish_reason)
                      .filter(model.execution_id.in_(ids)).all()
                      if row.truncated or row.finish_reason == "length"}
            for execution in executions:
                if execution.status == "failed":
                    execution.final_score = 0.0
                elif execution.id in capped and execution.status in {"completed", "awaiting_manual", "awaiting_judge"}:
                    execution.status = "failed"
                    execution.final_score = 0.0
                    execution.error_message = execution.error_message or "Token limit exhausted before generation finished"
            session.flush()
            _update_progress(session, run_id)
            if run.status == "completed" and run.failed_prompts:
                run.status = "completed_with_errors"
        # The updated attempt outcomes must be committed before summary reads.
        summary = compute_run_summary(run_id)
        with session_scope() as session:
            session.get(BenchmarkRun, run_id).summary = summary
    return len(run_ids)
