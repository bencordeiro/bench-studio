"""Pricing must survive profile edits and remain consistent in results/exports."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db.session import session_scope
from app.jobs import engine
from app.models import BenchmarkRun, PerformanceMetric
from app.schemas.endpoints import EndpointProfileCreate
from app.services import crud
from app.services.openai_client import ChatResult


@pytest.mark.parametrize("field", ["input_price_per_1m", "output_price_per_1m"])
@pytest.mark.parametrize("price", [-1, float("inf"), float("nan")])
def test_invalid_token_prices_are_rejected(field, price):
    with pytest.raises(ValidationError):
        EndpointProfileCreate(name="Invalid price", **{field: price})


@pytest.mark.parametrize("prompt_tokens,completion_tokens", [(None, 50), (100, None)])
def test_missing_priced_token_counts_do_not_understate_cost(prompt_tokens, completion_tokens):
    assert (
        engine._compute_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input_price_per_1m=2,
            output_price_per_1m=4,
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_usage", [False, True])
async def test_run_uses_saved_prices_and_exposes_cost_in_results_and_exports(monkeypatch, missing_usage):
    calls = 0

    async def fake_chat(*args, **kwargs):
        nonlocal calls
        calls += 1
        usage = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
        if missing_usage and calls == 2:
            del usage["prompt_tokens"]
        return ChatResult(
            content="yes",
            finish_reason="stop",
            truncated=False,
            usage=usage,
            http_status=200,
            time_to_first_token=0.1,
            total_response_time=0.5,
            retry_count=0,
        )

    monkeypatch.setattr(engine, "chat_completion", fake_chat)
    config = {"repetitions": 2}
    with session_scope() as session:
        profile = crud.create_endpoint_profile(
            session,
            {
                "name": "Priced provider",
                "base_url": "http://test/v1",
                "default_model": "m",
                "input_price_per_1m": 2,
                "output_price_per_1m": 4,
            },
        )
        duplicate = crud.duplicate_endpoint_profile(session, profile)
        assert (duplicate.input_price_per_1m, duplicate.output_price_per_1m) == (2, 4)
        benchmark = crud.create_benchmark_set(
            session,
            {
                "name": "Pricing test",
                "prompts": [
                    {
                        "stable_id": "p1",
                        "title": "Say yes",
                        "grading_mode": "deterministic",
                        "grader_config": {"type": "exact", "canonical_answer": "yes"},
                        "messages": [{"role": "user", "content": "Say yes"}],
                    }
                ],
            },
        )
        run = crud.create_run(
            session,
            {
                "benchmark_id": benchmark.id,
                "target_endpoint_id": profile.id,
                "target_model": "m",
                "run_config": config,
            },
        )
        run_id = run.id
        crud.update_endpoint_profile(
            session,
            profile,
            {
                "input_price_per_1m": 90,
                "output_price_per_1m": 90,
            },
        )
        assert run.benchmark_snapshot["target"]["input_price_per_1m"] == 2

    await engine.run_job(
        run_id,
        target_profile=profile,
        target_model="m",
        target_session_key=None,
        target_settings={},
        judge_profile=None,
        judge_model="",
        judge_session_key=None,
        judge_settings={},
        run_config=config,
        judge_enabled=False,
        verifier_enabled=False,
    )
    expected_costs = [0.004, None if missing_usage else 0.004]
    expected_total = None if missing_usage else 0.008
    with session_scope() as session:
        run = session.get(BenchmarkRun, run_id)
        assert run.status == "completed"
        assert run.summary["total_cost"] == expected_total
        assert [m.cost for m in session.query(PerformanceMetric).all()] == expected_costs

    from app.main import app

    with TestClient(app) as client:
        results = client.get(f"/api/runs/{run_id}/results").json()
        assert results["run"]["summary"]["total_cost"] == expected_total
        assert [e["timing"]["cost"] for e in results["executions"]] == expected_costs
        exported = client.get(f"/api/runs/{run_id}/export/json").json()
        assert exported["summary"]["total_cost"] == expected_total
        assert [p["timing"]["cost"] for p in exported["prompts"]] == expected_costs
        cost_text = "—" if missing_usage else "$0.008000"
        assert f'Total cost</div><div class="v">{cost_text}' in client.get(f"/api/runs/{run_id}/export/html").text
