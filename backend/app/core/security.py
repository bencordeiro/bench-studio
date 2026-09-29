"""Logging setup that never records secrets."""
from __future__ import annotations

import logging
import logging.handlers
import re
from typing import Any

from app.core.config import get_settings

SENSITIVE_KEYS = (
    "authorization",
    "api_key",
    "apikey",
    "api-key",
    "key",
    "token",
    "secret",
    "password",
    "x-api-key",
    "bearer",
)

_BEARER_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]+)", re.IGNORECASE)
_KEY_RE = re.compile(r"(\b(?:sk|tp|ttp)-[A-Za-z0-9_\-]{6,})")
_LONG_TOKEN_RE = re.compile(r"([A-Za-z0-9_\-]{32,})")


def sanitize(value: Any) -> Any:
    """Recursively redact secret-looking values from any JSON-ish structure or string."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize(v) for v in value)
    if isinstance(value, str):
        s = value
        s = _BEARER_RE.sub(r"\1[REDACTED]", s)
        s = _KEY_RE.sub("[REDACTED]", s)
        return s
    return value


class SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize(record.msg)
        if record.args:
            record.args = sanitize(record.args)
        return True


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    # Remove handlers that could double-log; keep our one.
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(SanitizingFilter())
    console.setLevel(level)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.addFilter(SanitizingFilter())
    file_handler.setLevel(level)
    root.addHandler(file_handler)
    root.setLevel(level)
