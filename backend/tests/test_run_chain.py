"""Ordered benchmark chains are atomic and use the existing single worker."""
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.db.session import session_scope
from app.jobs.runner import JobRunner, runner
from app.models import ApplicationSetting, BenchmarkRun, PromptExecution


def _suite(client, name, prompts=True):
    return client.post("/api/benchmarks", json={"name": name, "prompts": [
        {"stable_id": "p", "title": "P", "grading_mode": "deterministic",
         "grader_config": {"type": "exact", "canonical_answer": "yes"},
         "messages": [{"role": "user", "content": "Say yes"}]},
    ] if prompts else []}).json()["id"]


@pytest.fixture
def client(monkeypatch):
    from app.main import app

    # These API tests must never start a model request.
    monkeypatch.setattr(runner, "start", Mock())
    monkeypatch.setattr(runner, "notify", Mock())
    with TestClient(app) as c:
        yield c


def _endpoint(client):
    return client.post("/api/endpoints", json={"name": "Local", "base_url": "http://unused.invalid/v1"}).json()["id"]


def test_chain_creation_order_shared_settings_and_independent_snapshots(client):
    a, b = _suite(client, "A"), _suite(client, "B")
    eid = _endpoint(client)
    with session_scope() as s:
        s.add(ApplicationSetting(key="app", value={"default_max_tokens": 1234, "default_timeout": 75}))
    response = client.post("/api/runs/chain", json={
        "benchmark_ids": [b, a], "target_endpoint_id": eid, "target_model": "demo", "notes": "shared",
        "run_config": {"repetitions": 2, "temperature": 0.2, "max_tokens": 999, "timeout": 1},
    })
    assert response.status_code == 201, response.text
    runs = response.json()
    assert [r["benchmark_id"] for r in runs] == [b, a]
    assert [r["run_config"]["chain_position"] for r in runs] == [0, 1]
    assert len({r["run_config"]["chain_id"] for r in runs}) == 1
    for r in runs:
        assert r["status"] == "queued"
        assert r["total_prompts"] == 2
        assert r["target_model"] == "demo"
        assert r["notes"] == "shared"
        assert r["run_config"]["temperature"] == 0.2
        assert r["run_config"]["max_tokens"] == 1234
        assert r["run_config"]["timeout"] == 75
    runner.notify.assert_called_once()
    chain = client.get(f"/api/runs/{runs[0]['id']}/chain").json()
    assert [r["id"] for r in chain] == [r["id"] for r in runs]
    with session_scope() as s:
        stored = [s.get(BenchmarkRun, r["id"]) for r in runs]
        assert [r.benchmark_snapshot["name"] for r in stored] == ["B", "A"]
        assert s.query(PromptExecution).count() == 4
    # Cancelling a queued member must finish cancellation, without starting it.
    cancelled = client.post(f"/api/runs/{runs[0]['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["completed_at"]
    assert client.get(f"/api/runs/{runs[1]['id']}").json()["status"] == "queued"
    # Queue metadata survives reopening the app/session.
    assert client.get(f"/api/runs/{runs[1]['id']}/chain").json()[0]["status"] == "cancelled"


@pytest.mark.parametrize("bad", ["missing", "empty"])
def test_chain_creation_rolls_back_every_member_on_invalid_suite(client, bad):
    a = _suite(client, "A")
    second = "missing" if bad == "missing" else _suite(client, "Empty", prompts=False)
    response = client.post("/api/runs/chain", json={"benchmark_ids": [a, second], "target_endpoint_id": _endpoint(client)})
    assert response.status_code == 400
    assert client.get("/api/runs").json() == []
    with session_scope() as s:
        assert s.query(PromptExecution).count() == 0
    runner.notify.assert_not_called()


def test_chain_rejects_duplicates_and_empty_selection(client):
    a = _suite(client, "A")
    eid = _endpoint(client)
    for ids in ([], [a, a], [""]):
        assert client.post("/api/runs/chain", json={"benchmark_ids": ids, "target_endpoint_id": eid}).status_code == 422
    assert client.get("/api/runs").json() == []


async def test_worker_executes_in_queue_order_and_continues_after_failure(session):
    import uuid

    from app.models import BenchmarkSet

    suite = BenchmarkSet(id=str(uuid.uuid4()), name="B", version="1")
    session.add(suite)
    session.flush()
    ids = []
    for i in range(3):
        r = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=suite.id, status="queued", target_model="demo")
        session.add(r)
        session.flush()
        ids.append(r.id)
    session.commit()
    worker = JobRunner()
    visited = []

    async def execute(rid):
        assert worker.current_run_id == rid
        visited.append(rid)
        if rid == ids[0]:
            raise ValueError("Profile could not be loaded")
        with session_scope() as s:
            s.get(BenchmarkRun, rid).status = "completed"

    worker._execute_run = AsyncMock(side_effect=execute)
    assert await worker._process_one()
    assert await worker._process_one()
    assert await worker._process_one()
    assert not await worker._process_one()
    assert visited == ids
    assert worker.current_run_id is None

    session.expire_all()
    assert session.get(BenchmarkRun, ids[0]).status == "failed"
    assert session.get(BenchmarkRun, ids[0]).error_message == "Profile could not be loaded"
    assert session.get(BenchmarkRun, ids[0]).completed_at
