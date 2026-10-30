"""Mini Master is a faithful, independently selectable sampler of current suites."""
import copy
import json
import subprocess
import sys
from pathlib import Path

from app.models import BenchmarkRun, BenchmarkSet
from app.schemas.settings import DEFAULT_INDEX_SUITE_NAMES
from app.seed.suites_loader import SUITES_DIR, seed_bundled_suites

REPO = Path(__file__).resolve().parents[2]
MINI = json.loads((SUITES_DIR / "mini_master.json").read_text())


def test_mini_master_selection_and_exact_source_contracts():
    proc = subprocess.run([sys.executable, str(REPO / "scripts/build_mini_master_suite.py"), "--check"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert MINI["version"] == "3.0.0" and len(MINI["prompts"]) == 25
    assert "Mini Master" not in DEFAULT_INDEX_SUITE_NAMES
    counts = {}
    for prompt in MINI["prompts"]:
        source = next(t.split(":", 1)[1] for t in prompt["tags"] if t.startswith("source-suite:"))
        sid = next(t.split(":", 1)[1] for t in prompt["tags"] if t.startswith("source-id:"))
        suite = json.loads((SUITES_DIR / (source + ".json")).read_text())
        original = next(p for p in suite["prompts"] if p["stable_id"] == sid)
        assert prompt["messages"] == original["messages"]
        assert prompt["grader_config"] == original["grader_config"]
        assert prompt["grading_mode"] == original["grading_mode"]
        assert prompt["generation_overrides"] == original["generation_overrides"]
        assert f"source-version:{suite['version']}" in prompt["tags"]
        counts[source] = counts.get(source, 0) + 1
    assert counts == {"cyber": 4, "terminal_semantics": 4, "code_reasoning_python": 4,
                      "web_dev_js": 4, "agentic_tool_use": 4, "instruction_following": 3, "humaneval": 2}
    assert {p["importance_weight"] for p in MINI["prompts"]} == {3.0}
    retired = {"mm-math-multiset", "mm-math-gcd-triples", "mm-auto-intercooler", "mm-abs-raft",
               "mm-agent-error-recovery", "mm-context-config"}
    assert not retired.intersection(p["stable_id"] for p in MINI["prompts"])


def test_mini_master_upgrades_in_place_without_rewriting_history(session):
    import uuid

    seed_bundled_suites(session)
    bench = session.query(BenchmarkSet).filter_by(name="Mini Master").one()
    sid = bench.id
    old = copy.deepcopy(MINI)
    old["version"] = "2.0.0"
    bench.version = old["version"]
    run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=sid, status="completed",
                       benchmark_snapshot=old, run_config={})
    session.add(run)
    session.flush()
    assert seed_bundled_suites(session) == 1
    assert bench.id == sid and bench.version == "3.0.0" and len(bench.prompts) == 25
    assert run.benchmark_snapshot == old
    assert seed_bundled_suites(session) == 0
