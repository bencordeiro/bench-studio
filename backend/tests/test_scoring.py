"""Tests for scoring: quality, reliability, performance, composite, hybrid, caps."""
from __future__ import annotations

from app.graders import scoring


def test_category_quality_weighted():
    result = scoring.category_quality_score([(80, 1), (60, 2)])
    # (80*1 + 60*2) / 3 = 200/3
    assert abs(result - 66.67) < 0.1


def test_category_quality_no_weight_returns_none():
    assert scoring.category_quality_score([]) is None


def test_overall_quality_excludes_unscored():
    prompts = [
        {"score": 80, "weight": 1, "status": "completed"},
        {"score": None, "weight": 1, "status": "awaiting_manual"},
        {"score": 60, "weight": 2, "status": "completed"},
    ]
    score, scored, total = scoring.overall_quality_score(prompts)
    assert scored == 2
    assert total == 3
    # (80*1 + 60*2) / 3
    assert abs(score - 66.67) < 0.1


def test_overall_quality_all_unscored_returns_none():
    prompts = [{"score": None, "weight": 1, "status": "awaiting_manual"}]
    score, scored, total = scoring.overall_quality_score(prompts)
    assert score is None
    assert scored == 0


def test_reliability_perfect_factors():
    rel = scoring.reliability_score(
        {"completion": 1.0, "valid_response": 1.0, "structure": 1.0,
         "grade_parsed": 1.0, "no_truncation": 1.0},
        repetitions=1,
    )
    assert rel == 100.0


def test_reliability_zero_completion():
    rel = scoring.reliability_score(
        {"completion": 0.0, "valid_response": 0.0, "structure": 0.0,
         "grade_parsed": 0.0, "no_truncation": 0.0},
        repetitions=1,
    )
    # consistency weight still contributes (1.0 for n=1): 0.0*0.9 + 1.0*0.1
    assert abs(rel - 10.0) < 0.5


def test_consistency_score_uniform_is_one():
    assert scoring.consistency_score([80, 80, 80]) == 1.0


def test_consistency_score_variable_is_low():
    c = scoring.consistency_score([10, 90])
    assert c < 0.5


def test_performance_index_ideal():
    pi = scoring.performance_index(
        metrics=[{"time_to_first_token": 0.2, "output_tokens_per_second": 60, "failed": False}],
        thresholds={"desired_ttft": 0.5, "max_ttft": 5, "desired_tps": 40, "min_tps": 5, "max_failure_rate": 0.1},
    )
    assert pi == 100.0


def test_performance_index_all_failures():
    pi = scoring.performance_index(
        metrics=[{"time_to_first_token": 6, "output_tokens_per_second": 1, "failed": True}],
        thresholds={"desired_ttft": 0.5, "max_ttft": 5, "desired_tps": 40, "min_tps": 5, "max_failure_rate": 0.1},
    )
    assert pi == 0.0


def test_composite_default_weights():
    c = scoring.composite_score(quality=80, reliability=90, performance=70)
    # 80*.85 + 90*.10 + 70*.05 = 68 + 9 + 3.5 = 80.5
    assert abs(c - 80.5) < 0.1


def test_composite_missing_value_uses_contributed_weight():
    c = scoring.composite_score(quality=80, reliability=None, performance=None)
    # only quality contributed: 80*.85 / .85 = 80
    assert abs(c - 80.0) < 0.1


def test_composite_all_none_returns_none():
    assert scoring.composite_score(quality=None, reliability=None, performance=None) is None


def test_hybrid_score_weighted():
    s = scoring.hybrid_score(
        deterministic_fraction=1.0, judge_fraction=0.5,
        deterministic_weight=40, judge_weight=60,
    )
    # (1.0*40 + 0.5*60)/100 * 100 = 70
    assert abs(s - 70.0) < 0.1


def test_apply_score_cap_limits():
    capped, cap = scoring.apply_score_cap(85, 60)
    assert capped == 60
    assert cap == 60


def test_apply_score_cap_none():
    capped, cap = scoring.apply_score_cap(85, None)
    assert capped == 85
    assert cap is None


def test_repetition_stats_single():
    s = scoring.repetition_stats([50])
    assert s["mean"] == 50
    assert s["std"] == 0.0
    assert s["consistency"] == 1.0


def test_repetition_stats_multiple():
    s = scoring.repetition_stats([80, 82, 78])
    assert abs(s["mean"] - 80) < 0.1
    assert s["min"] == 78
    assert s["max"] == 82
    assert s["consistency"] > 0.9
