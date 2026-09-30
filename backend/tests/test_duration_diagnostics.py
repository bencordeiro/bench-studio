"""Duration diagnostics must use executable grading and preserve resumable data."""

import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app.services.openai_client import ChatResult

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from measure_suite_duration import grade_attempt, measure  # noqa: E402


def _result(content, **kwargs):
    return ChatResult(
        content=content,
        finish_reason=kwargs.get("finish_reason", "stop"),
        truncated=kwargs.get("truncated", False),
        usage={"completion_tokens": 20},
        http_status=200,
        time_to_first_token=0.1,
        total_response_time=1,
        retry_count=0,
    )


def test_generated_functions_are_graded_by_execution_and_exhaustion_is_zero():
    prompt = {
        "grading_mode": "execution",
        "messages": [{"content": "def double(n):\n"}],
        "grader_config": {
            "language": "python",
            "completion_mode": "full_function",
            "entry_point": "double",
            "timeout_seconds": 3,
            "test_code": "def check(candidate):\n    assert candidate(7) == 14\n",
        },
    }
    answer = "def double(n):\n    return n * 2\n"
    assert grade_attempt(prompt, _result(answer))["passed"]
    assert not grade_attempt(prompt, _result("def double(n):\n    return n\n"))["passed"]
    assert grade_attempt(prompt, _result(answer, finish_reason="length"))["score"] == 0


async def test_resume_skips_recorded_questions_and_refuses_changed_settings(tmp_path, monkeypatch):
    import measure_suite_duration as diagnostic

    fake = AsyncMock(return_value=_result("ANSWER: [2, 2, 2]"))
    monkeypatch.setattr(diagnostic, "chat_completion", fake)
    args = Namespace(
        suite="code_reasoning_python",
        base_url="http://unused.invalid/v1",
        model="demo",
        max_tokens=8192,
        reasoning_effort="medium",
        inactivity_timeout=60,
        observation_ceiling=300,
        out=str(tmp_path / "report.json"),
        resume=False,
        ids=["cr-closure-late-binding"],
        max_requests=1,
    )
    await measure(args)
    assert fake.await_count == 1
    assert (
        json.loads(Path(args.out).read_text())["records"]["cr-closure-late-binding"]["grade"]["score"] == 100
    )
    args.resume = True
    await measure(args)
    assert fake.await_count == 1
    args.reasoning_effort = "xhigh"
    with pytest.raises(ValueError, match="changed settings"):
        await measure(args)
    assert fake.await_count == 1


def test_summary_distinguishes_incorrect_answers_from_failed_generation():
    from measure_suite_duration import summarize

    report = {
        "suite_snapshot": {
            "prompts": [
                {"stable_id": "correct", "importance_weight": 1},
                {"stable_id": "wrong", "importance_weight": 2},
                {"stable_id": "capped", "importance_weight": 3},
            ]
        },
        "records": {
            "correct": {
                "finish_reason": "stop",
                "elapsed_seconds": 10,
                "grader_seconds": 0.1,
                "usage": {"completion_tokens": 100},
                "grade": {"score": 100, "passed": True},
            },
            "wrong": {
                "finish_reason": "stop",
                "elapsed_seconds": 20,
                "usage": {"completion_tokens": 200},
                "grade": {"score": 0, "passed": False},
            },
            "capped": {
                "finish_reason": "length",
                "elapsed_seconds": 30,
                "usage": {"completion_tokens": 8192},
                "grade": {"score": 0, "passed": False},
            },
        },
    }
    summary = summarize(report)
    assert summary["normal_finishes"] == 2
    assert summary["token_exhaustions"] == 1
    assert summary["grader_passes"] == 1
    assert summary["weighted_quality"] == 16.67
    assert summary["request_seconds"] == 60
    assert summary["maximum_request_seconds"] == 30
