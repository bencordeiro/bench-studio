"""Independent reviewed keys and adversarial controls for Cyber 2."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.graders.deterministic import run_deterministic
from app.seed.suites_loader import SUITES_DIR

REPO = Path(__file__).resolve().parents[2]
ANSWERS = {
    "cy2-iam-intersection": {"allowed": ["R1"], "explicit_deny": ["R4", "R5"]},
    "cy2-k8s-selector": {"ingress_matches": ["F1", "F6", "F7"], "allowed": ["F1", "F7"]},
    "cy2-jwt-binding": {"accepted": ["T1", "T5"], "buggy_only": ["T2", "T3", "T4"]},
    "cy2-ssrf-pinning": {"accepted": ["A", "F"], "rejected": [["B", 2], ["C", 1], ["D", 2], ["E", 1]]},
    "cy2-gcm-reservation": {"collisions": [["B1", "B4", 2], ["B2", "B6", 1], ["B3", "B4", 1]], "safe_repairs": ["B", "D"]},
    "cy2-alert-event-time": {"counts": [[10, "ipA", 4], [10, "ipB", 1], [14, "ipA", 4], [14, "ipB", 4]],
                             "alerts": [[10, "ipA"], [14, "ipA"], [14, "ipB"]]},
    "cy2-pid-reuse": {"targets": [[100, "P1"], [120, "P3"], [130, "P4"], [160, "P9"]], "exited_ancestors": ["P2", "P7"]},
    "cy2-http-framing": {"lengths": [["H1", 4], ["H6", 0], ["H7", 4]], "chunked": ["H4"], "reject_close": ["H2", "H3", "H5", "H8"]},
    "cy2-cache-tenant": {"hits": ["R2", "R4"], "leaked": ["R2", "R4"], "fixes": ["A", "C"]},
    "cy2-oidc-subject": {"policy_p": ["J1", "J2", "J3", "J6"], "policy_q": ["J1", "J3"], "excess": ["J2", "J6"]},
}
SUITE = json.loads((SUITES_DIR / "cyber.json").read_text())
PROMPTS = {p["stable_id"]: p for p in SUITE["prompts"]}


def test_cyber_bundle_matches_builder():
    result = subprocess.run([sys.executable, str(REPO / "scripts/build_cyber_suite.py"), "--check"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(PROMPTS) == set(ANSWERS)
    assert SUITE["version"] == "2.0.0"
    assert all(p["difficulty"] == "hard" and "unmeasured" in p["tags"] for p in PROMPTS.values())


@pytest.mark.parametrize("sid", ANSWERS)
def test_independent_cyber_keys_and_wrong_answers(sid):
    config = PROMPTS[sid]["grader_config"]
    expected = ANSWERS[sid]
    assert config["expected_field_values"] == expected
    assert run_deterministic(config, json.dumps(expected))["score"] == 100
    assert run_deterministic(config, json.dumps(dict(reversed(list(expected.items()))), indent=2))["score"] == 100
    for text in ("", "{}", "[]", "null", "I cannot answer", "```json\n" + json.dumps(expected) + "\n```",
                 json.dumps({**expected, "extra": True})):
        assert run_deterministic(config, text)["score"] == 0
    for key, value in expected.items():
        wrong = {**expected, key: None}
        assert run_deterministic(config, json.dumps(wrong))["score"] < 100
        if len(value) > 1:
            assert run_deterministic(config, json.dumps({**expected, key: list(reversed(value))}))["score"] < 100


@pytest.mark.parametrize("sid,key,wrong", [
    ("cy2-iam-intersection", "allowed", ["R1", "R2", "R3"]),
    ("cy2-k8s-selector", "allowed", ["F1", "F2", "F3", "F6", "F7"]),
    ("cy2-jwt-binding", "accepted", ["T1", "T2", "T3", "T4", "T5"]),
    ("cy2-ssrf-pinning", "accepted", ["A", "B", "C", "F"]),
    ("cy2-gcm-reservation", "safe_repairs", ["A", "B", "D"]),
    ("cy2-pid-reuse", "targets", [[100, "P1"], [110, "P5"], [120, "P3"], [130, "P4"], [140, "P6"], [150, "P8"], [160, "P9"]]),
    ("cy2-http-framing", "lengths", [["H1", 4], ["H6", 0]]),
    ("cy2-alert-event-time", "counts", [[10, "ipA", 5], [10, "ipB", 1], [14, "ipA", 5], [14, "ipB", 4]]),
])
def test_tempting_security_errors_lose_credit(sid, key, wrong):
    assert run_deterministic(PROMPTS[sid]["grader_config"], json.dumps({**ANSWERS[sid], key: wrong}))["score"] < 100
