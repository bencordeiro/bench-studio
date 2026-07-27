"""Tests for judge protocol: output validation and repair behavior."""
from __future__ import annotations

import json

from app.graders.judge_protocol import (
    build_judge_messages,
    parse_judge_output,
    parse_verifier_output,
)


VALID_JUDGE = {
    "dimension_scores": {
        "correctness": {"score": 36, "maximum": 40, "reason": "ok"},
        "completeness": {"score": 20, "maximum": 25, "reason": "ok"},
    },
    "raw_total": 56,
    "critical_error": False,
    "score_cap": None,
    "final_score": 88,
    "confidence": 0.9,
    "strengths": ["good"],
    "deductions": [{"points": 5, "reason": "missed step", "candidate_evidence": "none"}],
}


def test_parse_valid_judge():
    parsed, err = parse_judge_output(json.dumps(VALID_JUDGE))
    assert parsed is not None
    assert err == ""
    assert parsed.final_score == 88
    assert parsed.confidence == 0.9


def test_parse_judge_with_code_fence():
    fenced = "```json\n" + json.dumps(VALID_JUDGE) + "\n```"
    parsed, _ = parse_judge_output(fenced)
    assert parsed is not None
    assert parsed.final_score == 88


def test_parse_judge_with_prose_around():
    text = "Here is my evaluation:\n" + json.dumps(VALID_JUDGE) + "\nHope it helps."
    parsed, _ = parse_judge_output(text)
    assert parsed is not None


def test_parse_judge_invalid_json():
    parsed, err = parse_judge_output("not json at all")
    assert parsed is None
    assert "invalid JSON" in err


def test_parse_judge_schema_violation():
    bad = {"dimension_scores": {}, "final_score": 150, "confidence": 0.9, "raw_total": 0}
    parsed, err = parse_judge_output(json.dumps(bad))
    assert parsed is None
    assert "validation" in err.lower() or "schema" in err.lower()


def test_parse_judge_coerces_string_booleans():
    data = dict(VALID_JUDGE, critical_error="false")
    parsed, err = parse_judge_output(json.dumps(data))
    assert parsed is not None
    assert parsed.critical_error is False


def test_parse_judge_dimension_as_number_normalizes():
    data = {
        "dimension_scores": {"correctness": 36},
        "raw_total": 36,
        "final_score": 80,
        "confidence": 0.9,
    }
    parsed, _ = parse_judge_output(json.dumps(data))
    assert parsed is not None
    assert "correctness" in parsed.dimension_scores


def test_parse_judge_empty_returns_none():
    parsed, err = parse_judge_output("")
    assert parsed is None
    assert "empty" in err


def test_build_judge_messages_includes_rubric():
    msgs = build_judge_messages(
        original_messages=[{"role": "user", "content": "test"}],
        candidate_response="answer",
        config={"rubric_dimensions": [{"name": "correctness", "maximum": 40, "weight": 1, "description": "x"}],
                "required_elements": ["step1"], "critical_errors": ["bad"], "reference_answer": "ref"},
        extra_instructions="be strict",
    )
    assert msgs[0]["role"] == "system"
    assert "evaluator" in msgs[0]["content"].lower()
    user = msgs[1]["content"]
    assert "correctness" in user
    assert "step1" in user
    assert "be strict" in user
    assert "JSON" in user


def test_judge_does_not_require_exact_reference_wording():
    msgs = build_judge_messages(
        original_messages=[{"role": "user", "content": "q"}],
        candidate_response="a",
        config={"reference_answer": "specific answer"},
    )
    assert "guidance" in msgs[1]["content"].lower()


def test_parse_verifier_valid():
    data = {"confirmed": True, "verified_score": 88, "adjusted": False, "confidence": 0.9, "problems_found": []}
    parsed, err = parse_verifier_output(json.dumps(data))
    assert parsed is not None
    assert err == ""
    assert parsed.confirmed is True


def test_parse_verifier_invalid():
    parsed, err = parse_verifier_output("nope")
    assert parsed is None
