"""Repair derived scores from saved responses, without any endpoint requests."""
from __future__ import annotations

from itertools import product

from app.db.session import session_scope
from app.graders.deterministic import run_deterministic
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


def repair_terminal_comma_scores() -> int:
    """Recover correct saved WAL/Git answers rejected only for comma spacing."""
    from app.jobs.engine import compute_run_summary

    expected = {"ts-git-forensics": "3,3,1", "ts-sqlite-wal": "10,10,30"}
    finished = {"completed", "completed_with_errors", "failed", "cancelled"}
    with session_scope() as session:
        executions = (session.query(PromptExecution).join(BenchmarkRun)
                      .filter(BenchmarkRun.status.in_(finished), PromptExecution.status == "completed",
                              PromptExecution.prompt_snapshot_id.in_(expected), PromptExecution.final_score < 100)
                      .all())
        for execution in executions:
            prompt = execution.prompt_snapshot or {}
            config = prompt.get("grader_config") or {}
            run = execution.run
            if ((run.benchmark_snapshot or {}).get("name") != "Terminal Semantics & System Gotchas"
                    or prompt.get("grading_mode") != "deterministic"
                    or config.get("type") != "exact"
                    or config.get("canonical_answer") != expected[execution.prompt_snapshot_id]
                    or execution.manual_grade
                    or len(execution.target_response) != 1
                    or len(execution.deterministic_grades) != 1):
                continue
            response = execution.target_response[0]
            if response.truncated or response.finish_reason == "length" or any(
                metric.truncated or metric.finish_reason == "length" for metric in execution.performance_metrics
            ):
                continue
            parts = config["canonical_answer"].split(",")
            aliases = [parts[0] + a + parts[1] + b + parts[2]
                       for a, b in product((",", ", "), repeat=2)]
            updated = {**config, "accepted_aliases": list(config.get("accepted_aliases") or []) + aliases}
            result = run_deterministic(updated, response.content)
            if not result["passed"]:
                continue
            grade = execution.deterministic_grades[0]
            details = {"checks": result.get("checks", []), "repair": {
                "reason": "Accepted comma spacing permitted by the original prompt",
                "original_score": grade.score,
                "original_details": grade.details,
            }}
            grade.passed, grade.score, grade.max_score = True, result["score"], result["max_score"]
            grade.details = details
            execution.final_score = 100.0
            # Persist intent so a restart also finishes summary repair if it
            # occurs after grades commit but before cached summaries update.
            run.summary = {**(run.summary or {}), "terminal_comma_repair_pending": True}
        session.flush()
        run_ids = [rid for (rid,) in session.query(BenchmarkRun.id)
                   .filter(BenchmarkRun.status.in_(finished),
                           BenchmarkRun.summary["terminal_comma_repair_pending"].as_boolean().is_(True)).all()]
    for run_id in run_ids:
        summary = compute_run_summary(run_id)
        with session_scope() as session:
            session.get(BenchmarkRun, run_id).summary = summary
    return len(run_ids)
