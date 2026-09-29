"""The results endpoint: correctness of the batched child-row loading.

_build_execution_detail used to issue six queries per execution. The batched
loader must return byte-for-byte the same view, including for executions that
have no child rows at all.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_compatibility_failure_is_visible_in_run_api_and_json_export(session):
    from app.main import app
    from app.models import BenchmarkRun

    run_id = _seed_run_with_results(session)
    run = session.get(BenchmarkRun, run_id)
    report = {"status": "incompatible", "message": "Endpoint requires disabling its tool-call parser",
              "http_status": 400, "error": "HTTP 400: malformed tool call"}
    run.benchmark_snapshot = {**run.benchmark_snapshot, "text_tool_compatibility": report}
    run.status = "failed"
    run.error_message = report["message"]
    session.commit()
    with TestClient(app) as client:
        response = client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        assert response.json()["text_tool_compatibility"] == report
        exported = client.get(f"/api/runs/{run_id}/export/json")
        assert exported.status_code == 200
        assert exported.json()["run"]["text_tool_compatibility"] == report
        assert exported.json()["run"]["error_message"] == report["message"]


def _seed_run_with_results(session, prompt_count: int = 3):
    """A completed run whose last execution deliberately has no child rows."""
    from app.models import (
        BenchmarkRun,
        BenchmarkSet,
        DeterministicGrade,
        PerformanceMetric,
        PromptExecution,
        PromptStatus,
        RunStatus,
        TargetResponse,
    )

    bench = BenchmarkSet(id=str(uuid.uuid4()), name="B", version="1.0.0")
    session.add(bench)
    session.flush()

    run = BenchmarkRun(
        id=str(uuid.uuid4()),
        name="results run",
        status=RunStatus.COMPLETED.value,
        benchmark_id=bench.id,
        benchmark_snapshot={"name": "B", "version": "1.0.0", "prompts": []},
        target_model="m",
        run_config={"repetitions": 1},
        summary={},
        total_prompts=prompt_count,
        completed_prompts=prompt_count,
        failed_prompts=0,
    )
    session.add(run)

    for i in range(prompt_count):
        ex = PromptExecution(
            id=str(uuid.uuid4()),
            run_id=run.id,
            prompt_snapshot_id=f"p{i}",
            repetition=1,
            position=i,
            status=PromptStatus.COMPLETED.value,
            prompt_snapshot={
                "stable_id": f"p{i}",
                "title": f"Prompt {i}",
                "category": "cat",
                "grading_mode": "deterministic",
                "importance_weight": 1.0,
                "messages": [{"role": "user", "content": "q"}],
            },
            final_score=90.0 + i,
            max_score=100.0,
        )
        session.add(ex)
        # The last execution deliberately has no child rows.
        if i < prompt_count - 1:
            session.add(TargetResponse(
                id=str(uuid.uuid4()), execution_id=ex.id,
                content=f"answer {i}", finish_reason="stop", truncated=False, raw={},
            ))
            session.add(PerformanceMetric(
                id=str(uuid.uuid4()), execution_id=ex.id, request_start="now",
                time_to_first_token=0.2 + i, total_response_time=1.0 + i,
                completion_tokens=100 + i, output_tokens_per_second=50.0 + i,
                finish_reason="stop", http_status=200, retry_count=0,
                truncated=False, response_char_count=8,
            ))
            session.add(DeterministicGrade(
                id=str(uuid.uuid4()), execution_id=ex.id, grader_type="combined",
                passed=True, score=90.0 + i, max_score=100.0, details={"checks": []},
            ))
    session.flush()
    return run.id


def test_results_returns_child_rows_for_every_execution(session):
    from app.main import app

    run_id = _seed_run_with_results(session)
    session.commit()

    with TestClient(app) as c:
        r = c.get(f"/api/runs/{run_id}/results")
    assert r.status_code == 200
    body = r.json()

    execs = sorted(body["executions"], key=lambda e: e["position"])
    assert len(execs) == 3

    for i in (0, 1):
        assert execs[i]["candidate_response"] == f"answer {i}"
        assert execs[i]["timing"]["time_to_first_token"] == 0.2 + i
        assert execs[i]["timing"]["completion_tokens"] == 100 + i
        assert execs[i]["finish_reason"] == "stop"
        assert len(execs[i]["deterministics"]) == 1
        assert execs[i]["deterministics"][0]["score"] == 90.0 + i
        assert execs[i]["raw_meta"]["http_status"] == 200

    # An execution with no child rows must degrade gracefully, not raise.
    bare = execs[2]
    assert bare["candidate_response"] == ""
    assert bare["deterministics"] == []
    assert bare["judge"] is None
    assert bare["timing"]["time_to_first_token"] is None
    assert bare["raw_meta"]["http_status"] is None


def _count_result_selects(run_id: str) -> int:
    from sqlalchemy import event

    from app.db.session import get_engine
    from app.main import app

    statements: list[str] = []

    def before_cursor_execute(conn, cursor, statement, *args):
        statements.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with TestClient(app) as c:
            statements.clear()
            r = c.get(f"/api/runs/{run_id}/results")
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    assert r.status_code == 200
    return len([s for s in statements if s.lstrip().upper().startswith("SELECT")])


def test_results_query_count_does_not_scale_with_prompt_count(session):
    """Guards the N+1 regression directly: 4x the prompts, same query count.

    The old per-execution loading issued six queries per prompt, so a large
    suite turned one results page into hundreds of round trips.
    """
    small = _seed_run_with_results(session, prompt_count=3)
    large = _seed_run_with_results(session, prompt_count=12)
    session.commit()

    small_n = _count_result_selects(small)
    large_n = _count_result_selects(large)
    assert small_n == large_n, (
        f"query count grew with prompt count ({small_n} -> {large_n}); "
        "child rows are being loaded per execution again"
    )
