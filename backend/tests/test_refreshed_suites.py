"""Functional references, wrong implementations and retirement/upgrade coverage."""
import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.graders.deterministic import run_deterministic
from app.graders.execution import run_execution
from app.models import ApplicationSetting, BenchmarkPrompt, BenchmarkRun, BenchmarkSet, PromptMessage
from app.seed.suites_loader import SUITES_DIR, seed_bundled_suites

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from terminal_tasks import TASKS, prompts  # noqa: E402

AGENTIC_KEYS = {
    "ag5-paginated-join": [("get_invoice", {"invoice_id": "inv-2", "revision": 3}),
                           ("get_invoice", {"invoice_id": "inv-5", "revision": 7})],
    "ag5-versioned-patch": [("resize_pool", {"pool_id": "pool-eu", "new_size": 12,
                                             "expected_version": 6, "idempotency_key": "grow-91"})],
    "ag5-partial-outcomes": [("get_job_status", {"idempotency_key": "batch-7/2"}),
                             ("retry_job", {"job_id": "J3", "idempotency_key": "batch-7/3", "retry_token": "rt-38"})],
    "ag5-refund-ledger": [("refund_line", {"order_id": "O-17", "line_id": "L1", "amount_cents": 700, "reason": "return"}),
                          ("refund_line", {"order_id": "O-17", "line_id": "L2", "amount_cents": 1930, "reason": "return"})],
    "ag5-authoritative-identity": [("restore_backup", {"backup_id": "b-74", "target_id": "node-8", "expected_generation": 11})],
    "ag5-artifact-frontier": [("run_stage", {"stage_id": "test", "input_artifacts": ["bin@3", "schema@2"], "attempt": 3}),
                              ("run_stage", {"stage_id": "scan", "input_artifacts": ["bin@3"], "attempt": 1})],
}


@pytest.mark.parametrize("sid", AGENTIC_KEYS)
def test_independent_agentic_keys_and_argument_mutations(sid):
    import copy

    suite = json.loads((SUITES_DIR / "agentic_tool_use.json").read_text())
    prompt = next(p for p in suite["prompts"] if p["stable_id"] == sid)
    expected = [{"name": name, "arguments": args} for name, args in AGENTIC_KEYS[sid]]
    assert prompt["grader_config"]["expected_calls"] == expected
    def response(calls):
        return "\n".join("<tool_call>" + json.dumps(c) + "</tool_call>" for c in calls)
    assert run_deterministic(prompt["grader_config"], response(expected))["score"] == 100
    for i, call in enumerate(expected):
        for key, value in call["arguments"].items():
            wrong = copy.deepcopy(expected)
            wrong[i]["arguments"][key] = str(value) if isinstance(value, int) else None
            assert run_deterministic(prompt["grader_config"], response(wrong))["score"] < 100


@pytest.mark.parametrize("task,prompt", list(zip(TASKS, prompts())), ids=[t["name"] for t in TASKS])
def test_terminal_adaptation_references_and_incorrect_implementations(task, prompt):
    result = run_execution(prompt["grader_config"], task["reference"])
    assert result["passed"], result
    for wrong in [f"def {task['name']}(*args):\n    return []\n",
                  f"def {task['name']}(*args):\n    return None\n"]:
        assert not run_execution(prompt["grader_config"], wrong)["passed"]


def test_async_cleanup_harness_rejects_common_gather_bug():
    prompt = next(p for p in prompts() if p["grader_config"]["entry_point"] == "run_tasks")
    wrong = '''async def run_tasks(tasks, max_concurrent):
    import asyncio
    semaphore = asyncio.Semaphore(max_concurrent)
    async def run(factory):
        async with semaphore:
            await factory()
    await asyncio.gather(*(run(factory) for factory in tasks))
'''
    result = run_execution(prompt["grader_config"], wrong)
    assert not result["passed"], "gather does not clean up siblings when one raises"


def test_refresh_builder_and_removed_ids():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/build_refreshed_suites.py"), "--check"],
                          capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not (SUITES_DIR / "master_suite.json").exists()
    retired = {"ag-parallel-same", "ag-parallel-multiple", "ag-relevance-haiku", "ag-relevance-concept",
               "ag-arg-precision", "ag-missing-required-arg", "cr-mutable-default", "cr3-exception-chaining",
               "cr4-accumulator-dict", "cr-zip-strict-uneven", "cr-fn-latest-records", "cr-fn-missing-ranges"}
    for path in SUITES_DIR.glob("*.json"):
        assert retired.isdisjoint(p["stable_id"] for p in json.loads(path.read_text())["prompts"])


def test_retire_master_preserves_runs_and_custom_suites(session):
    bench = BenchmarkSet(id=str(uuid.uuid4()), name="Master Suite", version="5.0.0", tags=["master", "cross-domain"])
    custom = BenchmarkSet(id=str(uuid.uuid4()), name="Master Suite", version="1.0.0", tags=["custom"])
    session.add_all([bench, custom])
    session.flush()
    retired_id, custom_id = bench.id, custom.id
    prompt = BenchmarkPrompt(id=str(uuid.uuid4()), benchmark_id=retired_id, stable_id="old-master")
    message = PromptMessage(id=str(uuid.uuid4()), prompt_id=prompt.id, role="user", content="Historical definition")
    session.add_all([prompt, message])
    prompt_id, message_id = prompt.id, message.id
    run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=bench.id, status="completed", benchmark_snapshot={"name": "Master Suite"})
    session.add(run)
    settings = ApplicationSetting(key="app", value={"index_suite_ids": [bench.id, custom.id], "default_max_tokens": 8192})
    session.add(settings)
    session.flush()
    spec = importlib.util.spec_from_file_location("retire_master", ROOT / "backend/alembic/versions/0005_retire_master.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.op = Operations(MigrationContext.configure(session.connection()))
    migration.upgrade()
    session.expire_all()
    assert session.get(BenchmarkSet, retired_id) is None
    assert session.get(BenchmarkSet, custom_id) is not None
    assert session.get(BenchmarkPrompt, prompt_id) is None
    assert session.get(PromptMessage, message_id) is None
    assert session.get(BenchmarkRun, run.id).benchmark_snapshot == {"name": "Master Suite"}
    assert session.get(ApplicationSetting, "app").value == {"index_suite_ids": [custom_id], "default_max_tokens": 8192}
    migration.upgrade()


def test_all_five_refreshed_bundles_upgrade_existing_definitions(session):
    seed_bundled_suites(session)
    names = ["cyber", "terminal_semantics", "web_dev_js", "code_reasoning_python", "agentic_tool_use"]
    originals = {}
    for name in names:
        suite = json.loads((SUITES_DIR / (name + ".json")).read_text())
        bench = session.query(BenchmarkSet).filter_by(name=suite["name"]).one()
        originals[bench.id] = suite
        bench.version = "0.0.1"
        bench.prompts.clear()
    session.flush()
    assert seed_bundled_suites(session) == 5
    for sid, suite in originals.items():
        bench = session.get(BenchmarkSet, sid)
        assert bench.version == suite["version"]
        assert len(bench.prompts) == len(suite["prompts"])
