"""Executable contracts and adversarial regression checks for curated suites."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import indent

import pytest

from app.graders.deterministic import run_deterministic
from app.graders.execution import run_execution
from app.seed.suites_loader import SUITES_DIR

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_python_suite import execution_prompt  # noqa: E402 -- scripts are outside the app package
from python_tasks import TASKS  # noqa: E402


def suite(name):
    return json.loads((SUITES_DIR / f"{name}.json").read_text())


@pytest.mark.parametrize(
    "name,count",
    [
        ("instruction_following", 15),
        ("agentic_tool_use", 15),
        ("master_suite", 45),
        ("mini_master", 25),
        ("cyber", 18),
        ("terminal_semantics", 12),
        ("web_dev_js", 45),
        ("code_reasoning_python", 50),
    ],
)
def test_requested_suite_counts(name, count):
    prompts = suite(name)["prompts"]
    assert len(prompts) == count
    assert len({p["stable_id"] for p in prompts}) == count
    assert [p["position"] for p in prompts] == list(range(count))


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["name"])
def test_python_function_contract(task):
    p = execution_prompt(task)
    prefix = p["messages"][-1]["content"]
    result = run_execution(p["grader_config"], prefix + indent(task["body"], "    ") + "\n", prefix)
    assert result["passed"], result
    for wrong in ("    pass\n", "    return None\n", "    return []\n"):
        assert not run_execution(p["grader_config"], prefix + wrong, prefix)["passed"]


@pytest.mark.parametrize(
    "name,command", [("code_reasoning_python", [sys.executable, "-I", "-c"]), ("web_dev_js", ["node", "-e"])]
)
def test_output_prediction_answer_keys(name, command):
    if not shutil.which(command[0]):
        pytest.skip(f"{command[0]} not installed")
    for p in suite(name)["prompts"]:
        if p["grading_mode"] != "deterministic":
            continue
        result = subprocess.run(
            command + [p["messages"][-1]["content"]], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (p["stable_id"], result.stderr)
        assert result.stdout.strip() == p["grader_config"]["canonical_answer"], p["stable_id"]


def test_json_types_keys_and_object_shape():
    config = {
        "type": "json",
        "required_fields": ["value"],
        "expected_field_values": {"value": True},
        "allow_extra_fields": False,
        "allow_code_fences": False,
    }
    assert run_deterministic(config, '{"value":true}')["score"] == 100
    for response in (
        "[]",
        "[true]",
        '{"value":1}',
        '{"value":true,"extra":0}',
        '```json\n{"value":true}\n```',
    ):
        assert run_deterministic(config, response)["score"] < 100
    nested = {"type": "json", "expected_field_values": {"x": {"a": 1, "b": False}}}
    assert run_deterministic(nested, '{"x":{"b":false,"a":1}}')["score"] == 100
    assert run_deterministic(nested, '{"x":{"a":1,"b":0}}')["score"] < 100
    assert run_deterministic({"type": "json", "expected_field_values": {"x": None}}, "{}")["score"] == 0


def test_multiple_choice_does_not_match_letter_inside_wrong_prose():
    config = {"type": "multiple_choice", "correct_option": "C"}
    assert run_deterministic(config, "ANSWER: C")["score"] == 100
    assert run_deterministic(config, "ANSWER: B because dependencies conflict")["score"] == 0


def test_strict_hermes_rejects_wrong_types_names_and_envelopes():
    config = {
        "type": "tool_call",
        "strict_format": True,
        "strict_types": True,
        "strict_args": True,
        "expected_calls": [{"name": "book", "arguments": {"count": 4, "id": "Aa"}}],
    }
    valid = '<tool_call>{"name":"book","arguments":{"count":4,"id":"Aa"}}</tool_call>'
    assert run_deterministic(config, valid)["score"] == 100
    for bad in (
        valid.replace("4", '"4"'),
        valid.replace("Aa", "aa"),
        valid + "\nDone",
        valid + "<tool_call>",
        valid.replace("arguments", "parameters"),
        valid.replace('{"name"', '[{"name"').replace("}}</", "}}]</"),
    ):
        assert run_deterministic(config, bad)["score"] == 0, bad
    assert (
        run_deterministic(
            {"type": "tool_call", "expect_no_calls": True, "strict_format": True}, "<tool_call>"
        )["score"]
        == 0
    )


def test_invalid_regex_fails_closed():
    result = run_deterministic({"type": "regex", "required_patterns": ["["]}, "anything")
    assert not result["passed"] and result["score"] == 0


IF_RESPONSES = {
    "if-lipogram-bounded": "A hash map links IDs to data via hashing for fast lookup. Its slots hold pairs and collisions call for probing or chains.",
    "if-strict-json-schema": '{"name":"quicksort","average_complexity":"n log n","stable":false,"in_place":true}',
    "if-bullets-keyword-end": "- Tests catch bugs early.\n- Good tests document behavior.\n- They enable safe refactoring.\nShip with confidence.",
    "if-title-sections-nodigits": "<<Backup Policy>>\nSECTION: Storage\nKeep backups offline and secure.\nSECTION: Recovery\nPractice restoring files regularly.",
    "if-oneword-quoted": '"No"',
    "if-exact-words-forbidden": "A vast salty expanse teeming with life stretching far beyond the distant fading horizon line",
    "if-json-computed": '{"word_count":4,"last_word":"fox","reversed":"fox brown quick the"}',
    "if-placeholders-postscript": "Please submit your status report by [date].\nSend it to [manager].\nP.S. Include blockers",
    "if-alphabetical-acrostic": "Teams share tasks.\nEveryone contributes ideas.\nAll members listen.\nMembers support each other.",
    "if-nested-json-array": '{"count":3,"items":["apple","banana","cherry"]}',
    "if-case-and-repetition": "My ROUTINE starts at dawn. A ROUTINE includes breakfast. The ROUTINE ends with a walk.",
    "if-delimiter-sections": "###SUMMARY###\nVersion control preserves history and supports collaboration.\n###KEYWORDS###\nhistory,branches,review\n###END###",
    "if-priority-untrusted-data": '{"ids":["a1","b2"],"count":2}',
    "if-csv-escaping": 'id,label,note\n7,"west, zone","He said ""go"""\n8,plain,NULL',
    "if-conditional-redaction": '{"records":[{"id":"A","email":null},{"id":"C","email":"C@x.test"},{"id":"B","email":null}]}',
}


@pytest.mark.parametrize("p", suite("instruction_following")["prompts"], ids=lambda p: p["stable_id"])
def test_every_instruction_has_a_compliant_response(p):
    result = run_deterministic(p["grader_config"], IF_RESPONSES[p["stable_id"]])
    assert result["score"] == 100, result


def test_bullet_prompt_discloses_its_minimum_word_count():
    prompt = next(p for p in suite("instruction_following")["prompts"]
                  if p["stable_id"] == "if-bullets-keyword-end")
    assert "at least 15 words in total across the bullets and closing sentence" in prompt["messages"][0]["content"]
    short = "- tests catch bugs early.\n- tests document expected behavior.\n- Enable safe refactoring.\nShip with confidence."
    boundary = short.replace("Enable safe refactoring.", "Enable much safer refactoring.")
    config = prompt["grader_config"]
    result = run_deterministic(config, short)
    assert not result["passed"] and result["gate_failed"]
    length = next(check for check in result["checks"] if check["details"].get("count") == 14)
    assert not length["passed"]
    assert run_deterministic(config, boundary)["score"] == 100


@pytest.mark.parametrize(
    "sid,bad",
    [
        ("if-strict-json-schema", "[]"),
        ("if-oneword-quoted", '"no"'),
        ("if-placeholders-postscript", "Please submit the report.\nThanks.\nP.S. No placeholders"),
        ("if-alphabetical-acrostic", "Teams work.\n\nEveryone helps.\nAll listen.\nMembers share."),
        ("if-case-and-repetition", "ROUTINE ROUTINE ROUTINE starts at dawn. I eat. I walk."),
        ("if-delimiter-sections", "extra\n" + IF_RESPONSES["if-delimiter-sections"]),
        ("if-csv-escaping", 'id,label,note\n7,west, zone,He said "go"\n8,plain,'),
        ("if-priority-untrusted-data", "DONE"),
        (
            "if-conditional-redaction",
            '{"records":[{"id":"A","email":"a@x.test"},{"id":"C","email":"C@x.test"},{"id":"B","email":"b@x.test"}]}',
        ),
    ],
)
def test_instruction_violations_lose_credit(sid, bad):
    p = next(p for p in suite("instruction_following")["prompts"] if p["stable_id"] == sid)
    assert run_deterministic(p["grader_config"], bad)["score"] < 100


def _resolve_alternatives(value):
    if isinstance(value, dict) and set(value) == {"any_of"}:
        return value["any_of"][0]
    return value


@pytest.mark.parametrize("p", suite("agentic_tool_use")["prompts"], ids=lambda p: p["stable_id"])
def test_every_hermes_item_has_positive_and_negative_controls(p):
    prose = {
        "ag-relevance-haiku": "Autumn leaves fall softly\nBranches sway in the wind\nGolden paths await",
        "ag-relevance-concept": "Supply and demand change exchange rates, while interest rates influence how investors move their money between currencies.",
        "ag-missing-required-arg": "What is your destination?",
    }
    gc = p["grader_config"]
    calls = [spec for c in gc.get("checks", [gc]) for spec in c.get("expected_calls", [])]
    response = prose.get(p["stable_id"]) or "\n".join(
        "<tool_call>"
        + json.dumps(
            {
                "name": spec["name"],
                "arguments": {k: _resolve_alternatives(v) for k, v in spec["arguments"].items()},
            }
        )
        + "</tool_call>"
        for spec in calls
    )
    assert run_deterministic(gc, response)["score"] == 100
    assert (
        run_deterministic(gc, response + '\n<tool_call>{"name":"invented","arguments":{}}</tool_call>')[
            "score"
        ]
        < 100
    )
    if calls:
        wrong = "<tool_call>" + json.dumps({"name": calls[0]["name"], "arguments": {}}) + "</tool_call>"
        assert run_deterministic(gc, wrong)["score"] == 0


def test_json_rejects_duplicate_keys_and_nonfinite_numbers():
    gc = {"type": "json", "expected_field_values": {"value": 1}}
    for text in ['{"value":0,"value":1}', '{"value":1,"other":NaN}', '{"value":1,"other":Infinity}']:
        assert run_deterministic(gc, text)["score"] == 0
