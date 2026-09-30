"""Mini Master provenance, independent reference answers and output contracts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.graders.deterministic import run_deterministic
from app.models import BenchmarkSet
from app.seed.suites_loader import SUITES_DIR, seed_bundled_suites

REPO = Path(__file__).resolve().parents[2]
MINI = json.loads((SUITES_DIR / "mini_master.json").read_text())
PROMPTS = {p["stable_id"]: p for p in MINI["prompts"]}
MASTER = {p["stable_id"]: p for p in json.loads((SUITES_DIR / "master_suite.json").read_text())["prompts"]}
REFERENCES = {
    "mm-py-mutation-before-error": "ANSWER: True False 3 6",
    "mm-math-multiset": "ANSWER: 84",
    "mm-math-second-coin": "ANSWER: 0.4625",
    "mm-math-gcd-triples": "ANSWER: 624",
    "mm-cs-slru": '{"hits":11,"probation":["E","C"],"protected":["B","A"]}',
    "mm-cs-vector-clock": '{"clock":[4,2,4]}',
    "mm-cs-transaction": '{"balances":{"A":75,"B":15,"C":5},"committed":["k1","k2","k3"]}',
    "mm-sci-rolling": "ANSWER: 141.875",
    "mm-auto-intercooler": "ANSWER: 58.85",
    "mm-abs-raft": '{"supported":false,"fault_model":"CRASH"}',
    "mm-abs-underdetermined": '{"supported":false,"products":[21,24]}',
    "mm-context-config": '{"region":"ap","workers":8,"audit":true}',
    "mm-context-ledger": '{"balance":155,"applied":["e1","e2","e5","e6","e7"]}',
    "mm-agent-id-propagation": '<tool_call>{"name":"get_invoices","arguments":'
                               '{"customer_id":"cus_7Kd92Lm","status":"unpaid","since":"2026-04-30"}}</tool_call>',
    "mm-agent-error-recovery": '<tool_call>{"name":"create_event","arguments":'
                              '{"title":"Design sync","start":"2026-03-09T14:00",'
                              '"duration_minutes":45,"timezone":"Europe/Berlin"}}</tool_call>',
    "mm-agent-precondition-refusal": "Cannot transfer: available balance 120.50 is insufficient for 500.",
}


def test_mini_master_bundle_is_current_and_excludes_problem_items():
    result = subprocess.run([sys.executable, str(REPO / "scripts/build_mini_master_suite.py"), "--check"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert MINI["name"] == "Mini Master" and MINI["version"] == "2.0.0"
    assert len(PROMPTS) == len(MINI["prompts"]) == 23
    assert [p["position"] for p in MINI["prompts"]] == list(range(23))
    assert set(PROMPTS).isdisjoint(MASTER)
    excluded = {"ms-py-class-scope-comprehension", "ms-math-multiplicative-order",
                "ms-math-lcm-matrix-determinant", "ms-cs-natural-mergesort",
                "ms-cs-dynamic-array-copies", "ms-abs-false-output-claim",
                "ms-py-singledispatch-ambiguity", "ms-py-exception-groups", "ms-js-structured-clone"}
    assert not {"mm-py-singledispatch-ambiguity", "mm-py-exception-groups", "mm-js-structured-clone"} & set(PROMPTS)
    for prompt in PROMPTS.values():
        sources = [t.removeprefix("source-") for t in prompt["tags"] if t.startswith("source-ms-")]
        if prompt["stable_id"] == "mm-py-mutation-before-error":
            assert not sources and "original" in prompt["tags"]
            continue
        assert len(sources) == 1 and sources[0] in MASTER and sources[0] not in excluded


@pytest.mark.parametrize("sid,response", REFERENCES.items())
def test_mini_master_independent_reference_answers(sid, response):
    config = PROMPTS[sid]["grader_config"]
    assert run_deterministic(config, response)["score"] == 100
    for garbage in ("", "{}", "[]", "I don't know.", "ANSWER: 42"):
        assert run_deterministic(config, garbage)["score"] == 0


def test_mini_master_retained_code_matches_master():
    codes = [p for p in PROMPTS.values() if p["category"].startswith("code-reasoning/")]
    assert len(codes) == 8
    retained = [p for p in codes if "master-derived" in p["tags"]]
    assert len(retained) == 7
    for prompt in retained:
        original = MASTER["ms-" + prompt["stable_id"].removeprefix("mm-")]
        assert prompt["messages"] == original["messages"]
        assert prompt["grader_config"] == original["grader_config"]
        answer = "ANSWER: " + prompt["grader_config"]["canonical_answer"]
        assert run_deterministic(prompt["grader_config"], answer)["score"] == 100


def test_mini_master_wrong_policy_and_format_answers_are_penalized():
    wrong = {
        "mm-py-mutation-before-error": "ANSWER: True False 1 4",  # Incorrectly roll back mutation on TypeError.
        "mm-cs-vector-clock": '{"clock":[4,2,3]}',  # Forget the receive increment.
        "mm-cs-transaction": '{"balances":{"A":60,"B":30,"C":5},"committed":["k1","k2","k3"]}',
        "mm-abs-raft": '{"supported":true,"fault_model":"BYZANTINE"}',
        "mm-abs-underdetermined": '{"supported":true,"products":[25]}',
        "mm-context-config": '{"region":"ap","workers":99,"audit":false}',  # Untrusted note wins.
        "mm-context-ledger": '{"balance":135,"applied":["e1","e2","e2","e5","e6","e7"]}',
    }
    for sid, response in wrong.items():
        assert run_deterministic(PROMPTS[sid]["grader_config"], response)["score"] < 100
    for sid, response in REFERENCES.items():
        config = PROMPTS[sid]["grader_config"]
        if config.get("type") != "json":
            continue
        for bad in ("```json\n" + response + "\n```", json.dumps({**json.loads(response), "extra": True})):
            assert run_deterministic(config, bad)["score"] == 0
    for sid, rounded in (("mm-sci-rolling", "ANSWER: 141.88"), ("mm-auto-intercooler", "ANSWER: 58.9")):
        assert run_deterministic(PROMPTS[sid]["grader_config"], rounded)["score"] == 100


def test_mini_master_context_variants_are_compact():
    compact = [p for p in PROMPTS.values() if p["category"].startswith("context-synthesis/")]
    assert len(compact) == 2
    for prompt in compact:
        size = sum(len(m["content"]) for m in prompt["messages"])
        assert size < 4000
        source = next(t.removeprefix("source-") for t in prompt["tags"] if t.startswith("source-ms-"))
        assert size < sum(len(m["content"]) for m in MASTER[source]["messages"]) / 3


def test_mini_master_seeds_automatically_with_global_limits(session):
    seed_bundled_suites(session)
    suite = session.query(BenchmarkSet).filter_by(name="Mini Master").one()
    assert len(suite.prompts) == 23
    assert seed_bundled_suites(session) == 0
    for prompt in suite.prompts:
        assert prompt.grading_mode == "deterministic"
        assert "max_tokens" not in (prompt.generation_overrides or {})
        assert "unmeasured" in prompt.tags


def test_mini_master_upgrade_removes_retired_questions_in_place(session):
    seed_bundled_suites(session)
    suite = session.query(BenchmarkSet).filter_by(name="Mini Master").one()
    original_id = suite.id
    suite.version = "1.0.0"
    suite.prompts[0].stable_id = "mm-py-singledispatch-ambiguity"
    session.flush()
    assert seed_bundled_suites(session) == 1
    upgraded = session.get(BenchmarkSet, original_id)
    assert upgraded.version == "2.0.0"
    assert len(upgraded.prompts) == 23
    assert "mm-py-singledispatch-ambiguity" not in {p.stable_id for p in upgraded.prompts}
    assert "mm-py-mutation-before-error" in {p.stable_id for p in upgraded.prompts}
    assert seed_bundled_suites(session) == 0
