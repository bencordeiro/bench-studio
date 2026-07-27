"""Tests for deterministic graders."""
from __future__ import annotations

from app.graders.deterministic import run_deterministic


def test_count_words_max_pass_and_fail():
    cfg = {"type": "count", "unit": "words", "max": 5}
    assert run_deterministic(cfg, "one two three")["passed"] is True
    assert run_deterministic(cfg, "one two three four five six")["passed"] is False


def test_count_exact_bullets():
    cfg = {"type": "count", "pattern": r"(?m)^\s*[-*] ", "exact": 3}
    good = "* alpha\n* beta\n* gamma"
    bad = "* alpha\n* beta"
    assert run_deterministic(cfg, good)["passed"] is True
    assert run_deterministic(cfg, bad)["passed"] is False


def test_count_keyword_frequency_and_sentences():
    twice = {"type": "count", "pattern": r"\bdata\b", "exact": 2}
    assert run_deterministic(twice, "Data drives data.")["passed"] is True  # case-insensitive
    assert run_deterministic(twice, "data data data")["passed"] is False
    sentences = {"type": "count", "unit": "sentences", "min": 3}
    assert run_deterministic(sentences, "A. B! C?")["passed"] is True
    assert run_deterministic(sentences, "Only one.")["passed"] is False


def test_count_invalid_pattern_is_safe():
    r = run_deterministic({"type": "count", "pattern": "([", "exact": 1}, "x")
    assert r["passed"] is False
    assert "error" in r["checks"][0]["details"]


def test_exact_match_pass():
    r = run_deterministic(
        {"type": "exact", "canonical_answer": "Paris", "accepted_aliases": ["paris, france"]},
        "The answer is Paris.",
    )
    assert r["passed"] is True
    assert r["score"] == 100.0


def test_exact_alias_match():
    r = run_deterministic(
        {"type": "exact", "canonical_answer": "Paris", "accepted_aliases": ["City of Light"]},
        "Final answer: City of Light",
    )
    assert r["passed"] is True


def test_exact_match_case_insensitive_by_default():
    r = run_deterministic(
        {"type": "exact", "canonical_answer": "PARIS", "case_sensitive": False},
        "paris",
    )
    assert r["passed"] is True


def test_exact_match_case_sensitive_fails_when_different():
    r = run_deterministic(
        {"type": "exact", "canonical_answer": "Paris", "case_sensitive": True},
        "paris",
    )
    assert r["passed"] is False


def test_normalization_strips_punctuation():
    r = run_deterministic(
        {"type": "exact", "canonical_answer": "yes", "normalize_punctuation": True},
        "The answer is: yes.",
    )
    assert r["passed"] is True


def test_numeric_within_absolute_tolerance():
    r = run_deterministic(
        {"type": "numeric", "expected_value": 42, "absolute_tolerance": 0.5},
        "Final answer: 42.3",
    )
    assert r["passed"] is True


def test_numeric_outside_tolerance_fails():
    r = run_deterministic(
        {"type": "numeric", "expected_value": 42, "absolute_tolerance": 0.1},
        "The numbers 1, 2, and 50 appear. Answer: 50",
    )
    # Should extract the final-answer line value, not the first number.
    assert r["passed"] is False


def test_numeric_with_required_unit_pass():
    r = run_deterministic(
        {"type": "numeric", "expected_value": 100, "absolute_tolerance": 1, "required_unit": "m",
         "unit_aliases": ["meters"]},
        "Answer: 100 m",
    )
    assert r["passed"] is True


def test_numeric_wrong_unit_partial_credit():
    r = run_deterministic(
        {"type": "numeric", "expected_value": 100, "absolute_tolerance": 1, "required_unit": "m"},
        "Answer: 100 ft",
    )
    assert r["passed"] is False
    assert r["score"] == 50.0  # value correct, unit wrong


def test_numeric_no_number_fails():
    r = run_deterministic(
        {"type": "numeric", "expected_value": 100, "absolute_tolerance": 1},
        "I cannot compute this.",
    )
    assert r["passed"] is False
    assert r["score"] == 0.0


def test_regex_required_present():
    r = run_deterministic(
        {"type": "regex", "required_patterns": [r"\berror\b"]},
        "An error occurred.",
    )
    assert r["passed"] is True


def test_regex_forbidden_violated():
    r = run_deterministic(
        {"type": "regex", "forbidden_patterns": [r"rm\s+-rf"]},
        "Run rm -rf / to clean up.",
    )
    assert r["passed"] is False


def test_regex_no_forbidden_passes():
    r = run_deterministic(
        {"type": "regex", "forbidden_patterns": [r"rm\s+-rf"]},
        "Use a targeted delete command.",
    )
    assert r["passed"] is True


def test_concept_required_all_present():
    r = run_deterministic(
        {"type": "concept", "required_concepts": ["encryption", "certificate"], "points_per_concept": 50},
        "HTTPS uses encryption and a certificate.",
    )
    assert r["passed"] is True
    assert r["score"] == 100.0


def test_concept_forbidden_claim_present_caps():
    r = run_deterministic(
        {"type": "concept", "required_concepts": ["encryption"], "forbidden_claims": ["HTTP is secure by default"], "points_per_concept": 50},
        "encryption is used. HTTP is secure by default.",
    )
    assert r["passed"] is False


def test_concept_aliases_match():
    r = run_deterministic(
        {"type": "concept", "required_concepts": ["TLS"], "aliases": {"TLS": ["SSL"]}, "points_per_concept": 100},
        "The site uses SSL.",
    )
    assert r["passed"] is True


def test_json_valid_with_required_fields():
    r = run_deterministic(
        {"type": "json", "required_fields": ["name", "age"]},
        '{"name": "Ada", "age": 34}',
    )
    assert r["passed"] is True


def test_json_missing_field_fails():
    r = run_deterministic(
        {"type": "json", "required_fields": ["name", "age"]},
        '{"name": "Ada"}',
    )
    assert r["passed"] is False
    assert 0 < r["score"] < 100


def test_json_invalid_fails():
    r = run_deterministic(
        {"type": "json", "required_fields": ["name"]},
        "not json at all",
    )
    assert r["passed"] is False
    assert r["score"] == 0.0


def test_json_code_fences_allowed():
    r = run_deterministic(
        {"type": "json", "required_fields": ["x"], "allow_code_fences": True},
        "```json\n{\"x\": 1}\n```",
    )
    assert r["passed"] is True


def test_json_expected_field_value():
    r = run_deterministic(
        {"type": "json", "expected_field_values": {"age": 34}, "required_fields": []},
        '{"age": 34}',
    )
    assert r["passed"] is True


def test_multiple_choice_letter():
    r = run_deterministic(
        {"type": "multiple_choice", "correct_option": "B", "accepted_formats": ["Option B"]},
        "B",
    )
    assert r["passed"] is True


def test_multiple_choice_full_text():
    r = run_deterministic(
        {"type": "multiple_choice", "correct_option": "B", "accepted_formats": ["Ottawa"]},
        "Ottawa",
    )
    assert r["passed"] is True


def test_multiple_choice_wrong():
    r = run_deterministic(
        {"type": "multiple_choice", "correct_option": "B"},
        "C",
    )
    assert r["passed"] is False


def test_combined_checks_average():
    r = run_deterministic(
        {"checks": [
            {"type": "exact", "canonical_answer": "yes", "points": 100},
            {"type": "regex", "required_patterns": ["nope"], "points": 100},
        ]},
        "yes",
    )
    # One passes (100), one fails (0) -> average 50.
    assert r["score"] == 50.0
    assert r["passed"] is False
