from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.graders.deterministic import run_deterministic
from app.services.native_tools import native_request, normalize_native_result
from app.services.openai_client import ChatResult
from app.services.tool_compatibility import requires_text_tool_calls


def prompts():
    folder = Path(__file__).resolve().parents[1] / "app" / "seed" / "suites"
    return [prompt for suite in ("master_suite", "agentic_tool_use")
            for prompt in json.loads((folder / f"{suite}.json").read_text())["prompts"]
            if requires_text_tool_calls(prompt)]


@pytest.mark.parametrize("prompt", prompts(), ids=lambda p: p["stable_id"])
def test_all_bundled_tool_scenarios_have_valid_native_histories(prompt):
    messages, tools = native_request(prompt["messages"])
    assert tools
    assert "<tools>" not in messages[0]["content"]
    assert "<tool_call>" not in messages[0]["content"]
    expected_names = set()
    for message in prompt["messages"]:
        if message["role"] == "system":
            # Schema is the final non-empty tools block, after the illustrative tags.
            text = message["content"].rsplit("<tools>", 1)[1].split("</tools>", 1)[0]
            expected_names |= {function["name"] for function in json.loads(text)}
    assert {tool["function"]["name"] for tool in tools} == expected_names
    outstanding = []
    for message in messages:
        if message["role"] == "assistant" and message.get("tool_calls"):
            assert not outstanding
            outstanding = [call["id"] for call in message["tool_calls"]]
            for call in message["tool_calls"]:
                assert isinstance(json.loads(call["function"]["arguments"]), dict)
        elif message["role"] == "tool":
            assert message["tool_call_id"] == outstanding.pop(0)
        else:
            assert not outstanding
    assert not outstanding
    if prompt["stable_id"] == "ag-missing-required-arg":
        assert "reply exactly: What is your destination?" in messages[0]["content"]
    if prompt["stable_id"] == "ag-retry-state-idempotency":
        assert "quantity to 200" in next(m["content"] for m in messages if m["role"] == "tool")


def make_result(arguments, content=""):
    return ChatResult(content=content, finish_reason="tool_calls", truncated=False, usage={},
                      http_status=200, time_to_first_token=None, total_response_time=1, retry_count=0,
                      tool_calls=[{"id": "one", "type": "function", "function": {
                          "name": "get_weather", "arguments": arguments,
                      }}])


@pytest.mark.parametrize("arguments,passed", [
    ('{"location":"Paris","unit":"celsius"}', True),
    ('{"location":"Tokyo","unit":"celsius"}', False),
    ('{"location":"Paris","unit":"celsius","extra":1}', False),
    ('{"location":"Paris","unit":"celsius"', False),
    ('{"location":"Tokyo","location":"Paris","unit":"celsius"}', False),
    ('[]', False),
])
def test_native_argument_grading_preserves_wrong_and_malformed_values(arguments, passed):
    prompt = next(p for p in prompts() if p["stable_id"] == "ag-simple-weather")
    result = normalize_native_result(make_result(arguments))
    assert run_deterministic(prompt["grader_config"], result.content)["passed"] is passed
    assert result.raw["native_tool_calls"][0]["function"]["arguments"] == arguments
    assert result.raw["tool_call_protocol"] == "native"


def test_native_call_with_prose_still_fails_call_only_constraint():
    prompt = next(p for p in prompts() if p["stable_id"] == "ag-simple-weather")
    result = normalize_native_result(make_result('{"location":"Paris","unit":"celsius"}', "Here you go"))
    assert not run_deterministic(prompt["grader_config"], result.content)["passed"]


def test_native_history_missing_a_tool_result_is_not_fabricated():
    prompt = next(p for p in prompts() if p["stable_id"] == "ms-agent-id-propagation")
    with pytest.raises(ValueError, match="without the supplied tool results"):
        native_request(prompt["messages"][:-1])
