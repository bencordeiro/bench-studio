"""Deleting runs: cascades to executions, and refuses in-flight runs."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _make_run(status: str = "completed") -> str:
    from app.db.session import session_scope
    from app.models import BenchmarkRun, PromptExecution

    rid = str(uuid.uuid4())
    with session_scope() as s:
        s.add(BenchmarkRun(id=rid, benchmark_id="b", status=status, target_model="m",
                           benchmark_snapshot={"name": "S"}, summary={}))
        s.add(PromptExecution(id=str(uuid.uuid4()), run_id=rid, status="completed",
                              prompt_snapshot={}))
    return rid


def test_delete_completed_run_cascades(temp_data_dir):
    from app.db.session import session_scope
    from app.models import BenchmarkRun, PromptExecution

    rid = _make_run("completed")
    with _client() as c:
        assert c.delete(f"/api/runs/{rid}").status_code == 204
        assert c.get(f"/api/runs/{rid}").status_code == 404
    with session_scope() as s:
        assert s.get(BenchmarkRun, rid) is None
        assert s.query(PromptExecution).filter_by(run_id=rid).count() == 0


def test_delete_failed_run_allowed(temp_data_dir):
    with _client() as c:
        assert c.delete(f"/api/runs/{_make_run('failed')}").status_code == 204


def test_cannot_delete_the_in_flight_run(temp_data_dir):
    """The run the job runner is currently executing cannot be deleted."""
    from app.jobs.runner import runner

    rid = _make_run("completed")
    with _client() as c:
        runner._current_run_id = rid  # simulate this run being actively executed
        try:
            assert c.delete(f"/api/runs/{rid}").status_code == 409  # must cancel first
        finally:
            runner._current_run_id = None


def test_delete_missing_run_404(temp_data_dir):
    with _client() as c:
        assert c.delete("/api/runs/does-not-exist").status_code == 404


def test_clear_failed_runs(temp_data_dir):
    from app.db.session import session_scope
    from app.models import BenchmarkRun

    _make_run("failed")
    _make_run("failed")
    _make_run("completed")
    with _client() as c:
        r = c.post("/api/runs/clear-failed")
        assert r.status_code == 200
        assert r.json()["deleted"] == 2
    with session_scope() as s:
        assert s.query(BenchmarkRun).filter_by(status="failed").count() == 0
        assert s.query(BenchmarkRun).filter_by(status="completed").count() == 1
