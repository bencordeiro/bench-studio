"""Saved attempts are rescored locally, without repeating model requests."""
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.models import BenchmarkRun, BenchmarkSet, PromptExecution, TargetResponse
from app.services.scoring_repair import repair_saved_run_scores


def test_startup_repairs_historical_comparison_without_generation(session, monkeypatch):
    from app.jobs import engine
    from app.main import app

    chat = AsyncMock(side_effect=AssertionError("Rescoring must not generate"))
    monkeypatch.setattr(engine, "chat_completion", chat)
    suite = json.loads((Path(__file__).parents[1] / "app/seed/suites/mini_master.json").read_text())
    bench = BenchmarkSet(id=str(uuid.uuid4()), name="Mini Master", version="2.0.0", show_in_leaderboards=True)
    session.add(bench)
    session.flush()
    runs = []
    for model, scores in [
        ("ornith35b", [0, None, None, 0, 100, 100, None, 0] + [100] * 15),
        ("qwen27b_swift", [100, 100, 0, 0, 0, 100, 0, 100] + [100] * 15),
    ]:
        run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=bench.id, target_model=model,
                           status="completed_with_errors" if None in scores else "completed",
                           benchmark_snapshot=suite, run_config={"repetitions": 1},
                           summary={"quality_score": 83.19 if None in scores else 80.14}, total_prompts=23)
        session.add(run)
        runs.append(run.id)
        for i, (prompt, score) in enumerate(zip(suite["prompts"], scores, strict=True)):
            execution = PromptExecution(id=str(uuid.uuid4()), run_id=run.id,
                                        prompt_snapshot_id=prompt["stable_id"], prompt_snapshot=prompt,
                                        position=i, repetition=1,
                                        status="failed" if score is None else "completed", final_score=score)
            session.add(execution)
            session.add(TargetResponse(id=str(uuid.uuid4()), execution_id=execution.id,
                                       content="retained answer", finish_reason="stop", truncated=False,
                                       raw={"reasoning": "retained reasoning"}))
    session.commit()
    with TestClient(app) as client:
        history = {r["id"]: r for r in client.get("/api/runs").json()}
        assert history[runs[0]]["quality_score"] == 70.21
        assert history[runs[1]]["quality_score"] == 80.14
        comparison = client.get("/api/runs/compare", params=[("ids", rid) for rid in runs]).json()
        assert all(p["scores"][runs[0]] is not None for p in comparison["per_prompt"])
        results = client.get(f"/api/runs/{runs[0]}/results").json()
        assert results["summary"]["scoring_coverage"] == "23 of 23 prompts"
        failed = [e for e in results["executions"] if e["status"] == "failed"]
        assert len(failed) == 3
        assert all(e["final_score"] == 0 for e in failed)
        exported = client.get(f"/api/runs/{runs[0]}/export/json").json()
        assert all(p["score"] is not None for p in exported["prompts"])
        board = client.get(f"/api/leaderboards/{bench.id}?sort=quality&basis=best").json()
        assert [e["model"] for e in board["entries"]] == ["qwen27b_swift", "ornith35b"]
    assert repair_saved_run_scores() == 0
    chat.assert_not_called()
    session.expire_all()
    assert session.get(BenchmarkRun, runs[0]).benchmark_snapshot == suite
    assert all(t.raw["reasoning"] == "retained reasoning" for t in session.query(TargetResponse).all())


def test_repair_token_exhaustion_and_preserve_ungraded_and_summary_only(session):
    bench = BenchmarkSet(id=str(uuid.uuid4()), name="B", version="1")
    session.add(bench)
    session.flush()
    run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=bench.id, status="completed",
                       benchmark_snapshot={}, run_config={}, summary={}, total_prompts=3)
    imported = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=bench.id, status="completed",
                            summary={"quality_score": 88})
    session.add_all([run, imported])
    for i, (status, score) in enumerate([("completed", 100), ("awaiting_manual", None), ("completed", 100)]):
        execution = PromptExecution(id=str(uuid.uuid4()), run_id=run.id, prompt_snapshot_id=str(i),
                                    prompt_snapshot={"category": "cat", "importance_weight": 1},
                                    position=i, repetition=1, status=status, final_score=score)
        session.add(execution)
        if i == 0:
            session.add(TargetResponse(id=str(uuid.uuid4()), execution_id=execution.id, content="partial",
                                       finish_reason="length", truncated=True, raw={"reasoning": "keep"}))
    session.commit()
    assert repair_saved_run_scores() == 1
    session.expire_all()
    repaired = session.get(BenchmarkRun, run.id)
    assert repaired.status == "completed_with_errors"
    assert repaired.failed_prompts == 1
    assert repaired.summary["quality_score"] == 50
    assert repaired.summary["category_scores"]["cat"] == 50
    assert repaired.summary["scoring_coverage"] == "2 of 3 prompts"
    assert session.get(BenchmarkRun, imported.id).summary == {"quality_score": 88}
    assert session.query(PromptExecution).filter_by(run_id=run.id, status="awaiting_manual").one().final_score is None
