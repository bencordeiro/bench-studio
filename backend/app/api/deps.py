"""Shared API dependencies and helpers."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import BenchmarkPrompt, BenchmarkRun, BenchmarkSet, EndpointProfile, PromptExecution


def get_profile_or_404(session: Session, profile_id: str) -> EndpointProfile:
    p = session.get(EndpointProfile, profile_id)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint profile not found")
    return p


def get_benchmark_or_404(session: Session, bench_id: str) -> BenchmarkSet:
    b = session.get(BenchmarkSet, bench_id)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Benchmark not found")
    return b


def get_prompt_or_404(session: Session, prompt_id: str) -> BenchmarkPrompt:
    p = session.get(BenchmarkPrompt, prompt_id)
    if p is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return p


def get_run_or_404(session: Session, run_id: str) -> BenchmarkRun:
    r = session.get(BenchmarkRun, run_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return r


def get_execution_or_404(session: Session, exec_id: str) -> PromptExecution:
    e = session.get(PromptExecution, exec_id)
    if e is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return e
