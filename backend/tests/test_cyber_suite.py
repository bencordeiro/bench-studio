"""Independent Cyber controls: correct policies, tempting errors and strict output."""
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
CYBER = SUITES_DIR / "cyber.json"

# Independently reviewed keys, rather than reading the builder's computed values.
ANSWERS = {
    "cy-tenant-object": {"vulnerable": ["A", "B"], "issue": "IDOR"},
    "cy-sql-identifier": {"vulnerable": ["A", "C"], "fix": "ALLOWLIST_COLUMN_MAP"},
    "cy-ssrf-redirect": {"issue": "SSRF", "fix": "VALIDATE_EVERY_REDIRECT_HOP"},
    "cy-csrf-get": {"issue": "CSRF", "fix": "POST_WITH_VALIDATED_CSRF_TOKEN"},
    "cy-dom-text-sink": {"unsafe": ["A", "C"], "fix": "TEXT_CONTENT"},
    "cy-path-boundary": {"contained": ["P1", "P3"], "fix": "COMMONPATH_EQUALS_ROOT"},
    "cy-jwt-claims": {"accepted": ["T1", "T6"]},
    "cy-tls-hostname": {"accept": False, "missing_check": "HOSTNAME_MATCH"},
    "cy-egress-cidr": {"allowed": ["F1", "F4"]},
    "cy-iam-deny": {"allowed": ["R1", "R5"], "r2_rule": "EXPLICIT_DENY"},
    "cy-linux-directory": {"can_replace": True, "fix": "REMOVE_GROUP_DIRECTORY_WRITE"},
    "cy-container-volume": {"writable": ["P2"]},
    "cy-gcm-nonce": {"issue": "GCM_NONCE_REUSE", "affected": ["confidentiality", "integrity"],
                     "fix": "PERSIST_COUNTER_OR_ROTATE_KEY"},
    "cy-password-storage": {"replacement": "B", "issue": "FAST_OFFLINE_GUESSING"},
    "cy-alert-window": {"alert_ips": ["203.0.113.61"]},
    "cy-process-lineage": {"terminate_pids": [100, 110, 120, 130]},
    "cy-patch-priority": {"priority": ["V3", "V1", "V4", "V2"]},
    "cy-http-framing": {"issue": "HTTP_REQUEST_SMUGGLING", "fix": "REJECT_AMBIGUOUS_FRAMING_AND_CLOSE"},
}

PROMPTS = {p["stable_id"]: p for p in json.loads(CYBER.read_text())["prompts"]}


def test_cyber_bundle_matches_builder():
    result = subprocess.run([sys.executable, str(REPO / "scripts/build_cyber_suite.py"), "--check"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(PROMPTS) == set(ANSWERS)
    assert len(PROMPTS) == 18
    assert {p["position"] for p in PROMPTS.values()} == set(range(18))


@pytest.mark.parametrize("sid", ANSWERS)
def test_cyber_correct_and_incorrect_responses(sid):
    config = PROMPTS[sid]["grader_config"]
    answer = ANSWERS[sid]
    assert run_deterministic(config, json.dumps(answer))["score"] == 100
    # Object-key order and whitespace do not change correctness.
    reordered = dict(reversed(list(answer.items())))
    assert run_deterministic(config, json.dumps(reordered, indent=2))["score"] == 100
    for response in ("", "{}", "[]", "null", "I cannot answer.",
                     "```json\n" + json.dumps(answer) + "\n```",
                     json.dumps({**answer, "explanation": "additional prose"})):
        assert run_deterministic(config, response)["score"] == 0
    for field, value in answer.items():
        wrong = dict(answer)
        wrong[field] = None
        assert run_deterministic(config, json.dumps(wrong))["score"] < 100
        if isinstance(value, list) and len(value) > 1:
            wrong[field] = list(reversed(value))
            assert run_deterministic(config, json.dumps(wrong))["score"] < 100


# Plausible policy mistakes must be penalized, even when the JSON is perfect.
@pytest.mark.parametrize("sid,wrong", [
    ("cy-path-boundary", {"contained": ["P1", "P2", "P3"], "fix": "COMMONPREFIX_EQUALS_ROOT"}),
    ("cy-jwt-claims", {"accepted": ["T1", "T3", "T6"]}),  # Expiration boundary.
    ("cy-egress-cidr", {"allowed": ["F1", "F2", "F3", "F4"]}),  # /20 and earlier deny.
    ("cy-iam-deny", {"allowed": ["R1", "R2", "R5"], "r2_rule": "MORE_SPECIFIC_ALLOW"}),
    ("cy-alert-window", {"alert_ips": ["203.0.113.60", "203.0.113.61", "203.0.113.62"]}),
    ("cy-process-lineage", {"terminate_pids": [100, 110, 120, 130, 210]}),
    ("cy-patch-priority", {"priority": ["V1", "V4", "V3", "V2"]}),  # CVSS-only sorting.
    ("cy-container-volume", {"writable": []}),
    ("cy-tls-hostname", {"accept": 0, "missing_check": "HOSTNAME_MATCH"}),  # Boolean != integer.
])
def test_cyber_plausible_policy_errors_are_penalized(sid, wrong):
    assert run_deterministic(PROMPTS[sid]["grader_config"], json.dumps(wrong))["score"] < 100


def test_cyber_duplicate_fields_are_rejected():
    config = PROMPTS["cy-tls-hostname"]["grader_config"]
    response = '{"accept":true,"accept":false,"missing_check":"HOSTNAME_MATCH"}'
    assert run_deterministic(config, response)["score"] == 0


def test_cyber_seeds_once_and_remains_deterministic(session):
    seed_bundled_suites(session)
    suite = session.query(BenchmarkSet).filter_by(name="Cyber").one()
    assert suite.version == "1.0.0"
    assert len(suite.prompts) == 18
    assert seed_bundled_suites(session) == 0
    for prompt in suite.prompts:
        assert prompt.grading_mode == "deterministic"
        assert prompt.grader_config["type"] == "json"
        assert "max_tokens" not in (prompt.generation_overrides or {})
        assert "unmeasured" in prompt.tags
