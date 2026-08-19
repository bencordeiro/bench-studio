"""Persistent job runner: sequential single-worker queue backed by SQLite.

A single background asyncio task drains queued jobs one at a time. Because
state lives in SQLite, closing the browser does not stop a job, and an
interrupted run is resumed on the next start.
"""
from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.jobs.engine import run_job, signal_cancel
from app.models import BenchmarkRun, EndpointProfile, PromptExecution, PromptStatus, RunStatus

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._wakeup = asyncio.Event()
        self._current_run_id: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def current_run_id(self) -> str | None:
        return self._current_run_id

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._wakeup = asyncio.Event()
            self._task = asyncio.create_task(self._loop_body())
            log.info("Job runner started")

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def notify(self) -> None:
        """Wake the runner to check for new queued jobs."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._wakeup.set)
        else:
            try:
                self._wakeup.set()
            except Exception:
                pass

    async def _loop_body(self) -> None:
        self._loop = asyncio.get_running_loop()
        log.info("Job runner loop active")
        while True:
            try:
                await self._process_one()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job runner iteration failed")
            # Wait either for a wakeup or poll periodically.
            try:
                self._wakeup.clear()
                await asyncio.wait_for(self._wakeup.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

    async def _process_one(self) -> None:
        with session_scope() as session:
            run = (
                session.query(BenchmarkRun)
                .filter(BenchmarkRun.status == RunStatus.QUEUED.value)
                .order_by(BenchmarkRun.created_at)
                .first()
            )
            if run is None:
                return
            run_id = run.id
        self._current_run_id = run_id
        try:
            await self._execute_run(run_id)
        finally:
            self._current_run_id = None

    async def _execute_run(self, run_id: str) -> None:
        # Load everything needed, resolving endpoint profiles (which may have
        # been deleted since; snapshots preserve settings). Extract all scalar
        # values inside the session so nothing is accessed after it closes.
        with session_scope() as session:
            run = session.get(BenchmarkRun, run_id)
            if run is None:
                return
            target_profile = (
                session.get(EndpointProfile, run.target_endpoint_id)
                if run.target_endpoint_id
                else None
            )
            judge_profile = (
                session.get(EndpointProfile, run.judge_endpoint_id)
                if run.judge_endpoint_id
                else None
            )
            target_settings = dict(run.target_settings or {})
            judge_settings = dict(run.judge_settings or {})
            run_config = dict(run.run_config or {})
            # If profiles were deleted, reconstruct minimal stand-ins from snapshot.
            if target_profile is None:
                target_profile = _profile_from_snapshot((run.benchmark_snapshot or {}).get("target") or {})
            if judge_profile is None and run.judge_endpoint_id:
                judge_profile = _profile_from_snapshot((run.benchmark_snapshot or {}).get("judge") or {})
            # Capture scalars before the session closes (avoids DetachedInstanceError).
            target_model = run.target_model
            judge_model = run.judge_model
            judge_enabled = run.judge_enabled
            verifier_enabled = run.verifier_enabled

        if target_profile is None:
            with session_scope() as session:
                run = session.get(BenchmarkRun, run_id)
                if run is not None:
                    run.status = RunStatus.FAILED.value
                    run.error_message = "Target endpoint profile not found."
            return

        await run_job(
            run_id,
            target_profile=target_profile,
            target_model=target_model,
            target_session_key=None,
            target_settings=target_settings,
            judge_profile=judge_profile,
            judge_model=judge_model,
            judge_session_key=None,
            judge_settings=judge_settings,
            run_config=run_config,
            judge_enabled=judge_enabled,
            verifier_enabled=verifier_enabled,
        )


def _profile_from_snapshot(snap: dict) -> EndpointProfile:
    """Reconstruct an EndpointProfile-like object from a snapshot.

    Secrets are not available in snapshots; the runner relies on env-var or
    keyring resolution. This keeps history valid even if the profile row was
    deleted.
    """
    return EndpointProfile(
        id=snap.get("id", "deleted"),
        name=snap.get("name", "(deleted profile)"),
        base_url=snap.get("base_url", ""),
        default_model=snap.get("default_model", ""),
        request_timeout=snap.get("request_timeout", 60.0),
        verify_tls=snap.get("verify_tls", True),
        custom_headers=snap.get("custom_headers", {}) or {},
        extra_body_params=snap.get("extra_body_params", {}) or {},
        has_api_key=snap.get("has_api_key", False),
        api_key_storage=snap.get("api_key_storage", "none"),
        api_key_env_var=snap.get("api_key_env_var", ""),
    )


# Singleton runner used app-wide.
runner = JobRunner()


def enqueue_run(run_id: str | None = None) -> None:
    """Wake the runner so it picks up newly-queued work.

    The caller is responsible for having committed the run in QUEUED status --
    this only rings the bell. ``run_id`` is accepted for call-site readability
    and is intentionally unused; the runner always drains by created_at order.
    """
    runner.notify()


def request_cancel(run_id: str) -> bool:
    """Request immediate cancellation (aborts the current in-flight request)."""
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return False
        if run.status in {
            RunStatus.COMPLETED.value,
            RunStatus.COMPLETED_WITH_ERRORS.value,
            RunStatus.CANCELLED.value,
            RunStatus.FAILED.value,
        }:
            return False
        run.status = RunStatus.CANCEL_REQUESTED.value
    if runner._loop and runner._loop.is_running():
        runner._loop.call_soon_threadsafe(signal_cancel, run_id)
    else:
        signal_cancel(run_id)
    runner.notify()
    return True


def resume_run(run_id: str) -> bool:
    """Resume an INTERRUPTED run from the first incomplete prompt."""
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        if run is None:
            return False
        if run.status != RunStatus.INTERRUPTED.value:
            return False
        # Reset any in-flight executions to pending.
        session.query(PromptExecution).filter(
            PromptExecution.run_id == run_id,
            PromptExecution.status == PromptStatus.RUNNING.value,
        ).update({PromptExecution.status: PromptStatus.PENDING.value}, synchronize_session=False)
        run.status = RunStatus.QUEUED.value
        run.error_message = ""
    runner.notify()
    return True
