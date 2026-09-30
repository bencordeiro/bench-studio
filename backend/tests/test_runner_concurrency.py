"""Endpoint scheduling tests use gated fake jobs, never model requests."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.db.session import session_scope
from app.jobs.runner import JobRunner, _endpoint_key
from app.models import BenchmarkRun, BenchmarkSet, EndpointProfile, PromptExecution


def _runs(session, urls, *, profiles=False):
    suite = BenchmarkSet(id=str(uuid.uuid4()), name="Concurrency", version="1")
    session.add(suite)
    session.flush()
    ids = []
    for i, url in enumerate(urls):
        endpoint_id = None
        if profiles:
            profile = EndpointProfile(id=str(uuid.uuid4()), name=f"Profile {i}", base_url=url)
            session.add(profile)
            session.flush()
            endpoint_id = profile.id
        run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=suite.id, status="queued",
                           target_model=f"model-{i}", target_endpoint_id=endpoint_id,
                           benchmark_snapshot={"target": {"base_url": url}},
                           created_at=datetime.now(timezone.utc) + timedelta(seconds=i))
        session.add(run)
        session.flush()
        ids.append(run.id)
    session.commit()
    return ids


@pytest.mark.parametrize("profiles", [True, False])
async def test_independent_endpoints_overlap_but_duplicates_keep_fifo(session, profiles):
    # A second profile and model using the same actual destination must wait.
    a, a2, b = _runs(session, ["http://ONE.invalid", "http://one.invalid:80/v1/", "http://two.invalid/v1"], profiles=profiles)
    worker = JobRunner()
    entered = {rid: asyncio.Event() for rid in (a, a2, b)}
    release = {rid: asyncio.Event() for rid in (a, a2, b)}
    visited = []

    async def execute(rid):
        visited.append(rid)
        with session_scope() as s:
            s.get(BenchmarkRun, rid).status = "running_target"
        entered[rid].set()
        await release[rid].wait()
        with session_scope() as s:
            s.get(BenchmarkRun, rid).status = "completed"

    worker._execute_run = AsyncMock(side_effect=execute)
    worker.start()
    try:
        await asyncio.wait_for(asyncio.gather(entered[a].wait(), entered[b].wait()), timeout=1)
        assert visited == [a, b]
        assert not entered[a2].is_set()
        assert worker.is_active(a) and worker.is_active(b)
        assert not worker.is_active(a2)
        release[a].set()
        # Completion wakes the scheduler immediately, despite B still running.
        await asyncio.wait_for(entered[a2].wait(), timeout=1)
        assert visited == [a, b, a2]
        assert worker.is_active(b)
        release[a2].set()
        release[b].set()
        await asyncio.gather(*(task for _, task in list(worker._active.values())))
    finally:
        await worker.shutdown()
    assert not worker._active


async def test_cancel_reserved_run_before_it_starts_finishes_cancellation(session, monkeypatch):
    import app.jobs.runner as runner_module

    (rid,) = _runs(session, ["http://unused.invalid/v1"])
    execution = PromptExecution(id=str(uuid.uuid4()), run_id=rid, status="pending", prompt_snapshot={})
    session.add(execution)
    session.commit()
    worker = JobRunner()
    monkeypatch.setattr(runner_module, "runner", worker)
    assert await worker._process_one()
    task = worker._active[rid][1]
    assert runner_module.request_cancel(rid)
    await task
    session.expire_all()
    run = session.get(BenchmarkRun, rid)
    assert run.status == "cancelled"
    assert run.completed_at
    assert session.get(PromptExecution, execution.id).status == "cancelled"
    assert not worker.is_active(rid)


async def test_cancel_one_active_run_does_not_cancel_other_endpoint(session, monkeypatch):
    import app.jobs.runner as runner_module

    a, b = _runs(session, ["http://a.invalid/v1", "http://b.invalid/v1"])
    worker = JobRunner()
    monkeypatch.setattr(runner_module, "runner", worker)
    started = {rid: asyncio.Event() for rid in (a, b)}
    release = {rid: asyncio.Event() for rid in (a, b)}
    monkeypatch.setattr(runner_module, "signal_cancel", lambda rid: release[rid].set())

    async def execute(rid):
        with session_scope() as s:
            s.get(BenchmarkRun, rid).status = "running_target"
        started[rid].set()
        await release[rid].wait()
        with session_scope() as s:
            run = s.get(BenchmarkRun, rid)
            run.status = "cancelled" if run.status == "cancel_requested" else "completed"

    worker._execute_run = AsyncMock(side_effect=execute)
    try:
        assert await worker._process_one()
        assert await worker._process_one()
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), timeout=1)
        a_task, b_task = worker._active[a][1], worker._active[b][1]
        assert runner_module.request_cancel(a)
        await a_task
        assert not worker.is_active(a)
        assert worker.is_active(b) and not b_task.done()
        release[b].set()
        await b_task
        session.expire_all()
        assert session.get(BenchmarkRun, a).status == "cancelled"
        assert session.get(BenchmarkRun, b).status == "completed"
    finally:
        await worker.shutdown()


@pytest.mark.parametrize("started", [False, True])
async def test_shutdown_cancels_all_jobs_and_releases_every_endpoint(session, started):
    ids = _runs(session, ["http://a.invalid/v1", "http://b.invalid/v1"])
    worker = JobRunner()
    entered = {rid: asyncio.Event() for rid in ids}

    async def execute(rid):
        entered[rid].set()
        await asyncio.Event().wait()

    worker._execute_run = AsyncMock(side_effect=execute)
    assert await worker._process_one()
    assert await worker._process_one()
    tasks = [task for _, task in worker._active.values()]
    if started:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered.values())), timeout=1)
    await worker.shutdown()
    assert all(task.cancelled() for task in tasks)
    assert not worker._active


def test_endpoint_identity_normalizes_url_but_distinguishes_ports_and_paths():
    assert _endpoint_key("http://HOST") == _endpoint_key("http://host:80/v1/")
    assert _endpoint_key("https://HOST/v1") == _endpoint_key("https://host:443/v1/")
    assert _endpoint_key("http://host:8000/v1") != _endpoint_key("http://host:8001/v1")
    assert _endpoint_key("https://host/one/v1") != _endpoint_key("https://host/two/v1")
