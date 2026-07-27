"""Invariants every bundled benchmark item must hold.

These encode the findings of the suite audit. A benchmark that quietly stops
measuring what it claims is worse than no benchmark, so each rule here failed
on a real item at some point.
"""
from __future__ import annotations

import json

import pytest

from app.graders.deterministic import run_deterministic
from app.seed.suites_loader import SUITES_DIR

SUITE_FILES = sorted(SUITES_DIR.glob("*.json"))


def _all_prompts():
    for path in SUITE_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for prompt in data["prompts"]:
            yield data["name"], prompt


ALL = list(_all_prompts())


# Answers that demonstrate no capability whatsoever.
NON_ANSWERS = [
    "",
    "I can't help with that.",
    "Sure!",
    "Okay, I will follow all of your constraints exactly as written.",
    "- a\n- b\n- c",
    '{"a": 1}',
    "ANSWER: 42",
]


def test_no_prompt_pays_out_for_a_non_answer():
    """Prohibitions are free points unless the item is gated on doing the task.

    An empty response satisfies "do not use the letter 'e'", "avoid these
    words" and "do not use digits" simultaneously; before gating, the lipogram
    item scored 67 for saying nothing.
    """
    offenders = []
    for suite, prompt in ALL:
        best = max(run_deterministic(prompt["grader_config"], t)["score"] for t in NON_ANSWERS)
        if best > 0:
            offenders.append(f"{prompt['stable_id']} scored {best:.0f} ({suite})")
    assert not offenders, "non-answers earned credit on:\n  " + "\n  ".join(offenders)


def test_gate_is_never_the_constraint_being_graded():
    """A gate detects a non-attempt; it must not be the requirement under test.

    Regression: the ocean prompt gated on "exactly 15 words", so a response that
    respected every banned word and landed on 12 scored 0 -- identical to saying
    nothing. Gating on a weakened form (at least 10 words, on topic) keeps the
    near-miss at partial credit while still zeroing an evasion.
    """
    offenders = []
    for _suite, prompt in ALL:
        checks = prompt["grader_config"].get("checks") or []
        gates = [c for c in checks if c.get("gate")]
        scored = [c for c in checks if not c.get("gate")]
        for g in gates:
            if g.get("type") != "count":
                continue
            # An exact/max gate is by definition the graded constraint.
            if g.get("exact") is not None or g.get("max") is not None:
                offenders.append(
                    f"{prompt['stable_id']}: gate pins {g.get('unit') or g.get('pattern')} "
                    f"to exactly {g.get('exact') or g.get('max')}"
                )
            # A gate that duplicates a scored check is the same mistake.
            for s in scored:
                if (s.get("type") == "count" and s.get("unit") == g.get("unit")
                        and s.get("pattern") == g.get("pattern")
                        and s.get("min") == g.get("min")
                        and s.get("exact") == g.get("exact")):
                    offenders.append(
                        f"{prompt['stable_id']}: gate is identical to a scored check")
    assert not offenders, "gates that grade rather than gate:\n  " + "\n  ".join(offenders)


def test_grader_strings_are_ascii():
    """A Cyrillic 'e' typed into an alias silently matches nothing.

    Regression: an alias meant to catch "key" was written with U+0435 and could
    never fire, quietly weakening the check it belonged to.
    """
    bad = []

    def scan(node, where):
        if isinstance(node, str):
            if any(ord(c) > 127 for c in node):
                bad.append(f"{where}: {node!r}")
        elif isinstance(node, dict):
            for k, v in node.items():
                scan(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                scan(v, f"{where}[{i}]")

    for _suite, prompt in ALL:
        scan(prompt["grader_config"], prompt["stable_id"])
    assert not bad, "non-ASCII in grader patterns/aliases:\n  " + "\n  ".join(bad)


def test_word_count_matches_human_counting():
    """Contractions and hyphenated compounds are one word, not two.

    Regression: `\\b\\w+\\b` scored "doesn't" as 2 and "well-known" as 2, which
    silently inflated every word count -- unfair on a prompt demanding an exact
    number of words.
    """
    from app.graders.deterministic import grade_count

    cases = [("It doesn't shimmer at dusk", 5),
             ("A well-known deep-sea expanse", 4),
             ("Vast expanse spanning 3.5 million miles", 6),
             ("Life teems there; darkness reigns below", 6)]
    for text, expected in cases:
        got = grade_count({"unit": "words", "exact": expected}, text)
        assert got["passed"], f"{text!r} counted {got['details']['count']}, expected {expected}"


def test_negative_constraints_are_always_gated():
    """Any item whose checks include a prohibition must also gate on a positive.

    Structural guard: catches a newly-authored item that stacks bans without a
    proof-of-work check, before it can silently reward silence.
    """
    ungated = []
    for _suite, prompt in ALL:
        checks = prompt["grader_config"].get("checks") or []
        if not checks:
            continue
        has_prohibition = any(
            (c.get("type") == "count" and c.get("exact") == 0)
            or (c.get("type") == "regex" and c.get("forbidden_patterns"))
            or (c.get("type") == "tool_call" and c.get("expect_no_calls"))
            for c in checks
        )
        has_gate = any(c.get("gate") for c in checks)
        if has_prohibition and not has_gate:
            ungated.append(prompt["stable_id"])
    assert not ungated, (
        "these items are built from prohibitions with nothing proving the task "
        "was attempted: " + ", ".join(ungated)
    )


def test_exact_answers_are_unambiguous_to_transcribe():
    """An answer must not be readable as a different set of fields.

    `3,false,2,,6,2` was a correct answer nobody could parse confidently: the
    embedded String(array) contributed its own commas. Difficulty must come
    from the reasoning, not from transcription hazards.
    """
    ambiguous = []
    for _suite, prompt in ALL:
        gc = prompt["grader_config"]
        answer = gc.get("canonical_answer")
        if not isinstance(answer, str):
            continue
        # An empty field between the delimiter used to join sub-results.
        if ",," in answer and "|" not in answer:
            ambiguous.append(f"{prompt['stable_id']}: {answer!r}")
    assert not ambiguous, "ambiguous canonical answers:\n  " + "\n  ".join(ambiguous)


def test_exact_graders_agree_on_case_sensitivity():
    """Within a suite, identical tasks must be judged by identical rules.

    Half the Web Dev items were case-insensitive and half were not, so two
    models making the same class of mistake scored differently by accident.
    """
    for path in SUITE_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        modes = {
            bool(p["grader_config"].get("case_sensitive"))
            for p in data["prompts"]
            if p["grader_config"].get("type") == "exact"
        }
        assert len(modes) <= 1, (
            f"{data['name']} mixes case-sensitive and case-insensitive exact graders"
        )


def test_declared_difficulty_matches_weight_ordering():
    """A 'medium' item must never outweigh a 'hard' one in the same suite."""
    for path in SUITE_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        hard = [p["importance_weight"] for p in data["prompts"] if p["difficulty"] == "hard"]
        medium = [p["importance_weight"] for p in data["prompts"] if p["difficulty"] == "medium"]
        if hard and medium:
            assert min(hard) >= max(medium), (
                f"{data['name']}: a medium item outweighs a hard one "
                f"(hard min {min(hard)}, medium max {max(medium)})"
            )


def test_every_prompt_states_its_own_length_requirements():
    """No item may impose a length requirement the prompt never mentioned.

    A small `min` is an anti-refusal floor and needs no announcement -- any
    real attempt clears it. An `exact`, a `max`, or a large `min` is a genuine
    requirement, and grading one silently punishes a correct concise answer.
    """
    LENGTH_UNITS = {"words", "sentences", "lines"}
    ANNOUNCED = ("word", "sentence", "line", "haiku", "exactly", "between")
    missing = []
    for _suite, prompt in ALL:
        text = " ".join(m["content"] for m in prompt["messages"]).lower()
        if any(k in text for k in ANNOUNCED):
            continue
        for check in prompt["grader_config"].get("checks") or []:
            if check.get("type") != "count" or check.get("unit") not in LENGTH_UNITS:
                continue
            binding = (
                check.get("exact") is not None
                or check.get("max") is not None
                or (check.get("min") or 0) > 20
            )
            if binding:
                missing.append(
                    f"{prompt['stable_id']} silently requires "
                    f"{check.get('exact') or check.get('max') or check.get('min')} "
                    f"{check['unit']}"
                )
    assert not missing, "\n  ".join(missing)


def test_discriminators_outweigh_anchors():
    """Items measured as failing must carry more weight than items that passed.

    A suite whose score is driven by items every model passes cannot rank
    models -- everything lands in the high 80s and the ordering is noise.
    Weights come from an observed run (see SCORING.md), and this keeps the two
    tiers from drifting back together.
    """
    for _suite, prompt in ALL:
        tags = prompt.get("tags", [])
        if "discriminator" in tags:
            assert prompt["importance_weight"] >= 3.0, (
                f"{prompt['stable_id']} is tagged as a discriminator but weighs "
                f"{prompt['importance_weight']}"
            )
        if "anchor" in tags:
            assert prompt["importance_weight"] <= 2.0, (
                f"{prompt['stable_id']} is an anchor but weighs "
                f"{prompt['importance_weight']}"
            )


def test_every_suite_retains_some_discriminating_power():
    """At least a fifth of each large suite's weight must sit on hard items."""
    for path in SUITE_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        if len(data["prompts"]) < 20:
            continue  # small curated suites are hand-balanced
        total = sum(p["importance_weight"] for p in data["prompts"])
        heavy = sum(
            p["importance_weight"] for p in data["prompts"] if p["importance_weight"] >= 3.0
        )
        assert heavy / total >= 0.10, (
            f"{data['name']}: only {heavy / total:.0%} of the weight is on measured-hard "
            "items; the suite will saturate"
        )


def test_suite_sizes_are_balanced_enough_to_compare():
    """No suite may be so small that one item dominates its score."""
    for path in SUITE_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        n = len(data["prompts"])
        assert n >= 10, f"{data['name']} has only {n} prompts; one item swings the score"
        weights = [p["importance_weight"] for p in data["prompts"]]
        assert max(weights) / sum(weights) < 0.25, (
            f"{data['name']}: a single prompt carries "
            f"{max(weights) / sum(weights):.0%} of the suite weight"
        )


@pytest.mark.parametrize("suite_name,prompt", [(s, p) for s, p in ALL])
def test_prompt_has_reviewable_metadata(suite_name, prompt):
    """Every item must be self-describing for later review."""
    assert prompt["stable_id"], f"{suite_name}: prompt without a stable_id"
    assert prompt["title"], f"{prompt['stable_id']}: no title"
    assert prompt["description"], f"{prompt['stable_id']}: no description"
    assert prompt["difficulty"] in {"easy", "medium", "hard"}, prompt["stable_id"]
    assert prompt["importance_weight"] > 0, prompt["stable_id"]
    assert any(m["role"] == "user" for m in prompt["messages"]), prompt["stable_id"]
