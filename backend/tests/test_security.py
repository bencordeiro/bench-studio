"""Tests for secret sanitization and logging safety."""
from __future__ import annotations

import logging

from app.core.security import sanitize, SanitizingFilter


def test_sanitize_redacts_bearer_token():
    out = sanitize("Authorization: Bearer sk-abc123def456")
    assert "sk-abc123def456" not in out
    assert "REDACTED" in out


def test_sanitize_redacts_sk_key():
    out = sanitize("error: sk-abcd1234efgh5678 in header")
    assert "sk-abcd1234efgh5678" not in out


def test_sanitize_redacts_dict_keys():
    out = sanitize({"api_key": "secret123", "other": "keep"})
    assert out["api_key"] == "[REDACTED]"
    assert out["other"] == "keep"


def test_sanitize_redacts_nested():
    out = sanitize({"headers": {"Authorization": "Bearer xyz123abc456def789ghi012"}})
    assert "xyz123abc456def789ghi012" not in str(out)


def test_sanitize_handles_lists():
    out = sanitize([{"api_key": "k"}, {"token": "t"}])
    assert out[0]["api_key"] == "[REDACTED]"
    assert out[1]["token"] == "[REDACTED]"


def test_sanitize_leaves_plain_text():
    assert sanitize("just a normal message") == "just a normal message"


def test_sanitizing_filter_redacts_record():
    rec = logging.LogRecord(
        "x", logging.INFO, "", 0, "key sk-abcdefgh1234567890 in here", None, None
    )
    flt = SanitizingFilter()
    assert flt.filter(rec) is True
    assert "sk-abcdefgh1234567890" not in str(rec.msg)


def test_sanitize_preserves_non_secret_long_strings():
    # A long random hash-like string that isn't a bearer/sk key is left alone.
    s = "id_" + "a" * 40
    out = sanitize(s)
    assert out == s
