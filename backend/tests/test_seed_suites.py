"""Bundled JSON suites: idempotent seeding + grader/answer consistency.

These tests guard every file in app/seed/suites/ so a new or edited suite can't
ship with an answer its own grader rejects.
"""
from __future__ import annotations

from app.graders.deterministic import run_deterministic
from app.models import BenchmarkPrompt, BenchmarkSet
from app.seed.suites_loader import SUITES_DIR, seed_bundled_suites


def _all_prompts(session):
    seed_bundled_suites(session)
    return session.query(BenchmarkPrompt).all()


def test_newer_bundled_version_upgrades_in_place(session):
    """A hardened suite must actually reach an existing DB, keeping its id."""
    seed_bundled_suites(session)
    bench = (
        session.query(BenchmarkSet)
        .filter(BenchmarkSet.name.like("Agentic Tool-Use%"))
        .one()
    )
    original_id, shipped_version = bench.id, bench.version

    # Simulate a DB still holding the older, weaker version of the suite.
    bench.version = "1.1.0"
    for p in list(bench.prompts)[2:]:
        bench.prompts.remove(p)
    session.flush()
    assert len(bench.prompts) == 2

    assert seed_bundled_suites(session) == 1
    upgraded = session.query(BenchmarkSet).filter(BenchmarkSet.id == original_id).one()
    assert upgraded.version == shipped_version
    assert len(upgraded.prompts) > 2
    # Re-running is now a no-op again.
    assert seed_bundled_suites(session) == 0


def test_local_edits_survive_when_version_is_unchanged(session):
    """Same version in the DB must never be clobbered by the seeder."""
    seed_bundled_suites(session)
    bench = session.query(BenchmarkSet).filter(BenchmarkSet.name.like("Agentic%")).one()
    bench.description = "my local notes"
    session.flush()
    assert seed_bundled_suites(session) == 0
    assert session.query(BenchmarkSet).filter(
        BenchmarkSet.id == bench.id
    ).one().description == "my local notes"


def test_bundled_suites_seed_and_are_idempotent(session):
    n_files = len(list(SUITES_DIR.glob("*.json")))
    assert n_files >= 3
    created = seed_bundled_suites(session)
    assert created == n_files
    assert session.query(BenchmarkSet).count() == n_files
    # Curated suites are leaderboard-eligible.
    assert all(b.show_in_leaderboards for b in session.query(BenchmarkSet).all())
    # Re-running must not duplicate.
    assert seed_bundled_suites(session) == 0
    assert session.query(BenchmarkSet).count() == n_files


def test_bundled_prompts_do_not_cap_max_tokens(session):
    """Suites must not force a low max_tokens — a chain-of-thought model would be
    truncated before its answer lands. Let the run config own the token budget."""
    for p in _all_prompts(session):
        go = p.generation_overrides or {}
        assert "max_tokens" not in go, (
            f"{p.stable_id} caps max_tokens ({go.get('max_tokens')}); remove it so the run controls it"
        )


def test_every_exact_canonical_answer_scores_100(session):
    """For each deterministic exact prompt, its own canonical answer (delivered
    as a realistic 'ANSWER: ...' reply) must earn a perfect score."""
    prompts = _all_prompts(session)
    exact_prompts = [p for p in prompts if p.grader_config.get("canonical_answer") is not None]
    assert len(exact_prompts) >= 20  # code (10) + web (12)
    for p in exact_prompts:
        answer = p.grader_config["canonical_answer"]
        result = run_deterministic(p.grader_config, f"reasoning...\nANSWER: {answer}")
        assert result["passed"], f"{p.stable_id}: grader rejected its own canonical answer"
        assert result["score"] == 100.0, f"{p.stable_id}: expected 100, got {result['score']}"


# A few known-compliant responses for the stacked-constraint (IFEval-style) prompts.
IF_COMPLIANT = {
    "if-strict-json-schema":
        '{"name": "quicksort", "average_complexity": "n log n", "stable": false, "in_place": true}',
    "if-bullets-keyword-end":
        "- Tests catch bugs early.\n- Good tests document behavior.\n"
        "- They enable safe refactoring.\nShip with confidence.",
    "if-exact-words-forbidden":
        "A vast salty expanse teeming with life stretching far beyond the distant "
        "fading horizon line",
    "if-json-computed":
        '{"word_count": 4, "last_word": "fox", "reversed": "fox brown quick the"}',
}


def test_instruction_following_compliant_responses_score_100(session):
    prompts = {p.stable_id: p for p in _all_prompts(session)}
    for sid, response in IF_COMPLIANT.items():
        assert sid in prompts, f"missing instruction-following prompt {sid}"
        result = run_deterministic(prompts[sid].grader_config, response)
        assert result["score"] == 100.0, f"{sid}: compliant response scored {result['score']}"


def test_instruction_following_violation_is_penalized(session):
    """A blatant violation must not score full marks (guards against no-op checks)."""
    prompts = {p.stable_id: p for p in _all_prompts(session)}
    p = prompts["if-lipogram-bounded"]
    result = run_deterministic(p.grader_config, "The keys are stored, and it is fast.")
    assert result["score"] < 100.0


# Correct Hermes-format tool calls for the agentic suite.
AGENTIC_COMPLIANT = {
    "ag-simple-weather":
        '<tool_call>{"name": "get_weather", "arguments": {"location": "Paris", "unit": "celsius"}}</tool_call>',
    "ag-parallel-same":
        '<tool_call>{"name": "get_weather", "arguments": {"location": "Paris", "unit": "celsius"}}</tool_call>\n'
        '<tool_call>{"name": "get_weather", "arguments": {"location": "Tokyo", "unit": "celsius"}}</tool_call>',
    "ag-relevance-haiku":
        "Crisp autumn morning\nred leaves drift on the cool wind\nsilence fills the grove",
}


def test_agentic_compliant_tool_calls_score_100(session):
    prompts = {p.stable_id: p for p in _all_prompts(session)}
    for sid, response in AGENTIC_COMPLIANT.items():
        assert sid in prompts, f"missing agentic prompt {sid}"
        result = run_deterministic(prompts[sid].grader_config, response)
        assert result["score"] == 100.0, f"{sid}: compliant call scored {result['score']}"


def test_agentic_relevance_penalizes_spurious_call(session):
    """Emitting a tool call when none is warranted must lose marks."""
    prompts = {p.stable_id: p for p in _all_prompts(session)}
    p = prompts["ag-relevance-haiku"]
    spurious = '<tool_call>{"name": "get_weather", "arguments": {"location": "autumn", "unit": "celsius"}}</tool_call>'
    assert run_deterministic(p.grader_config, spurious)["score"] < 100.0


def _tc(*calls: dict) -> str:
    import json as _json
    return "\n".join(f"<tool_call>{_json.dumps(c)}</tool_call>" for c in calls)


# Wrong answers that a whole-response regex grader used to score a perfect 100,
# because a pattern could match an argument belonging to a *different* call.
# (sid, label, response) -- every one must now score below 100.
AGENTIC_MUST_FAIL = [
    ("ag-simple-weather", "spurious extra call", _tc(
        {"name": "get_weather", "arguments": {"location": "Paris", "unit": "celsius"}},
        {"name": "send_email", "arguments": {"to": "bob"}})),
    ("ag-simple-weather", "malformed tool-call JSON",
     "<tool_call>{'name': get_weather,}</tool_call>"),
    ("ag-multiple-select", "describes the call instead of making it",
     "I would call get_stock_price with symbol AAPL, but I will not actually do it."),
    ("ag-multiple-hotel", "hallucinated dates", _tc(
        {"name": "search_hotels",
         "arguments": {"city": "Kyoto", "check_in": "2024-05-03", "check_out": "2024-05-07"}})),
    ("ag-parallel-same", "second call has the wrong unit", _tc(
        {"name": "get_weather", "arguments": {"location": "Paris", "unit": "celsius"}},
        {"name": "get_weather", "arguments": {"location": "Tokyo", "unit": "fahrenheit"}})),
    ("ag-arg-precision", "12-hour time where the schema demands 24-hour", _tc(
        {"name": "book_table",
         "arguments": {"restaurant": "Nobu", "party_size": 4, "time": "7:30 PM"}})),
    ("ag-missing-required-arg", "hallucinated the missing destination", _tc(
        {"name": "search_flights",
         "arguments": {"origin": "Denver", "destination": "New York", "date": "2026-04-12"}})),
    ("ag-nested-array-args", "attendees sent as a string, not an array", _tc(
        {"name": "create_event",
         "arguments": {"title": "Roadmap Review", "start": "2026-03-09T14:00",
                       "duration_minutes": 45, "attendees": "ana@corp.com, li@corp.com"}})),
    ("ag-enum-adherence", "conversion direction reversed", _tc(
        {"name": "convert_units", "arguments": {"value": 42, "from_unit": "mi", "to_unit": "km"}})),
    ("ag-parallel-three", "duplicated a ticker instead of the third", _tc(
        {"name": "get_stock_price", "arguments": {"symbol": "NVDA"}},
        {"name": "get_stock_price", "arguments": {"symbol": "AMD"}},
        {"name": "get_stock_price", "arguments": {"symbol": "AMD"}})),
    ("ag-iso-code-mapping", "full names instead of ISO codes", _tc(
        {"name": "convert_currency",
         "arguments": {"amount": 250, "from_currency": "pounds", "to_currency": "yen"}},
        {"name": "translate_text",
         "arguments": {"text": "thank you very much", "source_lang": "English",
                       "target_lang": "German"}})),
    ("ag-optional-arg-enum", "dropped the requested timeout", _tc(
        {"name": "run_query",
         "arguments": {"sql": "SELECT count(*) FROM orders", "database": "staging"}})),
]


def test_agentic_wrong_arguments_are_not_scored_correct(session):
    """Regression: the tool-use graders must bind arguments to their own call.

    Before the tool_call grader these all scored 100 -- a correct tool name with
    fabricated arguments passed, which made the whole suite unable to fail.
    """
    prompts = {p.stable_id: p for p in _all_prompts(session)}
    holes = []
    for sid, label, response in AGENTIC_MUST_FAIL:
        assert sid in prompts, f"missing agentic prompt {sid}"
        score = run_deterministic(prompts[sid].grader_config, response)["score"]
        if score >= 100.0:
            holes.append(f"{sid}: {label} scored {score}")
    assert not holes, "wrong answers scored a perfect 100:\n  " + "\n  ".join(holes)


def test_no_bundled_prompt_rewards_a_garbage_answer(session):
    """No prompt in any suite may hand full marks to a non-answer."""
    garbage = ["", "I don't know.", "Sorry, I cannot help with that.", "ANSWER: 42"]
    offenders = []
    for p in _all_prompts(session):
        best = max(run_deterministic(p.grader_config, g)["score"] for g in garbage)
        if best >= 100.0:
            offenders.append(f"{p.stable_id} (scored {best})")
    assert not offenders, "garbage answers earned 100 on: " + ", ".join(offenders)


def test_retiring_example_preserves_custom_suites_and_run_snapshots(session):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.models import BenchmarkRun
    from app.services.crud import create_benchmark_set

    example = create_benchmark_set(session, {'name':'LocalBench Studio Example Suite','prompts':[
        {'stable_id':'old-demo','title':'Old demo','messages':[{'role':'user','content':'Demo'}]}
    ]})
    example.is_example = True
    custom = create_benchmark_set(session, {'name':'LocalBench Studio Example Suite','prompts':[]})
    renamed = create_benchmark_set(session, {'name':'My edited example','prompts':[]})
    renamed.is_example = True
    snapshot = {'name':example.name,'prompts':[{'stable_id':'old-demo'}]}
    run = BenchmarkRun(id='historical-example-run',benchmark_id=example.id,benchmark_snapshot=snapshot)
    session.add(run)
    session.flush()
    example_id, custom_id, renamed_id = example.id, custom.id, renamed.id
    path = Path(__file__).resolve().parents[1]/'alembic/versions/0004_retire_example.py'
    spec = importlib.util.spec_from_file_location('retire_example',path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(session.connection())):
        migration.upgrade()
    session.expire_all()
    assert session.query(BenchmarkSet).filter_by(id=example_id).first() is None
    assert session.get(BenchmarkSet,custom_id) is not None
    assert session.get(BenchmarkSet,renamed_id) is not None
    assert session.query(BenchmarkPrompt).filter_by(benchmark_id=example_id).count() == 0
    assert session.get(BenchmarkRun,'historical-example-run').benchmark_snapshot == snapshot
