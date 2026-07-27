"""Benchmark sets, prompts, ordering, and import/export."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_benchmark_or_404, get_prompt_or_404
from app.db.session import get_db
from app.exports.benchmark_format import (
    build_models_from_export,
    parse_benchmark_export,
    serialize_benchmark,
)
from app.models import BenchmarkPrompt, BenchmarkSet, PromptMessage
from app.schemas import (
    BenchmarkPromptCreate,
    BenchmarkPromptResponse,
    BenchmarkSetCreate,
    BenchmarkSetResponse,
    BenchmarkSetSummary,
    BenchmarkSetUpdate,
)
from app.services import crud

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


def _prompt_to_response(p: BenchmarkPrompt, session: Session) -> BenchmarkPromptResponse:
    msgs = (
        session.query(PromptMessage)
        .filter(PromptMessage.prompt_id == p.id)
        .order_by(PromptMessage.position)
        .all()
    )
    return BenchmarkPromptResponse(
        id=p.id,
        benchmark_id=p.benchmark_id,
        stable_id=p.stable_id,
        title=p.title,
        description=p.description,
        category=p.category,
        tags=p.tags or [],
        difficulty=p.difficulty,
        importance_weight=p.importance_weight,
        position=p.position,
        enabled=p.enabled,
        grading_mode=p.grading_mode,
        generation_overrides=p.generation_overrides or {},
        grader_config=p.grader_config or {},
        messages=[{"role": m.role, "content": m.content, "position": m.position} for m in msgs],
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _bench_to_response(bench: BenchmarkSet, session: Session, include_prompts: bool = True) -> BenchmarkSetResponse:
    prompts = (
        session.query(BenchmarkPrompt)
        .filter(BenchmarkPrompt.benchmark_id == bench.id)
        .order_by(BenchmarkPrompt.position)
        .all()
    )
    return BenchmarkSetResponse(
        id=bench.id,
        name=bench.name,
        description=bench.description,
        version=bench.version,
        tags=bench.tags or [],
        scoring_config=bench.scoring_config or {},
        performance_thresholds=bench.performance_thresholds or {},
        composite_weights=bench.composite_weights or {},
        is_example=bench.is_example,
        show_in_leaderboards=bench.show_in_leaderboards,
        prompts=[_prompt_to_response(p, session) for p in prompts] if include_prompts else [],
        created_at=bench.created_at,
        updated_at=bench.updated_at,
    )


@router.get("", response_model=list[BenchmarkSetSummary])
def list_benchmarks(session: Session = Depends(get_db)):
    benches = session.execute(
        select(BenchmarkSet).order_by(BenchmarkSet.updated_at.desc())
    ).scalars().all()
    out = []
    for b in benches:
        count_q = select(func.count(BenchmarkPrompt.id)).where(
            BenchmarkPrompt.benchmark_id == b.id
        )
        total = session.execute(count_q).scalar_one()
        enabled = session.execute(
            count_q.where(BenchmarkPrompt.enabled.is_(True))
        ).scalar_one()
        out.append(BenchmarkSetSummary(
            id=b.id,
            name=b.name,
            description=b.description,
            version=b.version,
            tags=b.tags or [],
            is_example=b.is_example,
            show_in_leaderboards=b.show_in_leaderboards,
            created_at=b.created_at,
            updated_at=b.updated_at,
            prompt_count=total,
            enabled_prompt_count=enabled,
        ))
    return out


@router.post("", response_model=BenchmarkSetResponse, status_code=201)
def create_benchmark(payload: BenchmarkSetCreate, session: Session = Depends(get_db)):
    bench = crud.create_benchmark_set(session, payload.model_dump())
    session.commit()
    return _bench_to_response(bench, session)


@router.get("/{bench_id}", response_model=BenchmarkSetResponse)
def get_benchmark(bench_id: str, session: Session = Depends(get_db)):
    return _bench_to_response(get_benchmark_or_404(session, bench_id), session)


@router.put("/{bench_id}", response_model=BenchmarkSetResponse)
def update_benchmark(bench_id: str, payload: BenchmarkSetUpdate, session: Session = Depends(get_db)):
    bench = get_benchmark_or_404(session, bench_id)
    crud.update_benchmark_set(session, bench, payload.model_dump(exclude_unset=True))
    session.commit()
    return _bench_to_response(bench, session)


@router.delete("/{bench_id}", status_code=204)
def delete_benchmark(bench_id: str, session: Session = Depends(get_db)):
    bench = get_benchmark_or_404(session, bench_id)
    session.delete(bench)
    session.commit()


@router.post("/{bench_id}/duplicate", response_model=BenchmarkSetResponse)
def duplicate_benchmark(bench_id: str, session: Session = Depends(get_db)):
    bench = get_benchmark_or_404(session, bench_id)
    new = crud.duplicate_benchmark_set(session, bench)
    session.commit()
    return _bench_to_response(new, session)


@router.get("/{bench_id}/export")
def export_benchmark(bench_id: str, session: Session = Depends(get_db)):
    from fastapi.responses import Response

    bench = get_benchmark_or_404(session, bench_id)
    prompts = (
        session.query(BenchmarkPrompt)
        .filter(BenchmarkPrompt.benchmark_id == bench.id)
        .order_by(BenchmarkPrompt.position)
        .all()
    )
    msgs_by_prompt = {}
    for p in prompts:
        msgs_by_prompt[p.id] = (
            session.query(PromptMessage)
            .filter(PromptMessage.prompt_id == p.id)
            .order_by(PromptMessage.position)
            .all()
        )
    document = serialize_benchmark(bench, prompts, msgs_by_prompt)
    content = json.dumps(document, indent=2)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in bench.name)[:60]
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
    )


@router.post("/import", response_model=BenchmarkSetResponse)
async def import_benchmark(file: UploadFile = File(...), session: Session = Depends(get_db)):
    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    export, errors = parse_benchmark_export(data)
    if export is None:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    bench, prompts = build_models_from_export(export)
    session.add(bench)
    session.flush()
    for p in prompts:
        p.benchmark_id = bench.id
        session.add(p)
        session.flush()
        for m in p.messages:
            m.prompt_id = p.id
            session.add(m)
    session.commit()
    return _bench_to_response(bench, session)


# --------------------------------------------------------------------------- #
# Prompts within a benchmark
# --------------------------------------------------------------------------- #
@router.post("/{bench_id}/prompts", response_model=BenchmarkPromptResponse)
def create_prompt(bench_id: str, payload: BenchmarkPromptCreate, session: Session = Depends(get_db)):
    get_benchmark_or_404(session, bench_id)
    prompt = crud.upsert_prompt(session, bench_id, None, payload.model_dump())
    session.commit()
    return _prompt_to_response(prompt, session)


class PromptUpdate(BenchmarkPromptCreate):
    pass


@router.put("/{bench_id}/prompts/{prompt_id}", response_model=BenchmarkPromptResponse)
def update_prompt(bench_id: str, prompt_id: str, payload: PromptUpdate, session: Session = Depends(get_db)):
    prompt = get_prompt_or_404(session, prompt_id)
    if prompt.benchmark_id != bench_id:
        raise HTTPException(status_code=404, detail="Prompt not found in this benchmark")
    crud.upsert_prompt(session, bench_id, prompt_id, payload.model_dump(exclude_unset=True))
    session.commit()
    return _prompt_to_response(prompt, session)


@router.delete("/{bench_id}/prompts/{prompt_id}", status_code=204)
def delete_prompt(bench_id: str, prompt_id: str, session: Session = Depends(get_db)):
    prompt = get_prompt_or_404(session, prompt_id)
    if prompt.benchmark_id != bench_id:
        raise HTTPException(status_code=404, detail="Prompt not found in this benchmark")
    session.delete(prompt)
    session.commit()


@router.post("/{bench_id}/prompts/{prompt_id}/duplicate", response_model=BenchmarkPromptResponse)
def duplicate_prompt(bench_id: str, prompt_id: str, session: Session = Depends(get_db)):
    prompt = get_prompt_or_404(session, prompt_id)
    if prompt.benchmark_id != bench_id:
        raise HTTPException(status_code=404, detail="Prompt not found in this benchmark")
    new = crud.duplicate_prompt(session, prompt)
    session.commit()
    return _prompt_to_response(new, session)


class ReorderRequest(BaseModel):
    prompt_ids: list[str]


@router.post("/{bench_id}/reorder", response_model=BenchmarkSetResponse)
def reorder_prompts(bench_id: str, payload: ReorderRequest, session: Session = Depends(get_db)):
    get_benchmark_or_404(session, bench_id)
    crud.reorder_prompts(session, bench_id, payload.prompt_ids)
    session.commit()
    bench = get_benchmark_or_404(session, bench_id)
    return _bench_to_response(bench, session)
