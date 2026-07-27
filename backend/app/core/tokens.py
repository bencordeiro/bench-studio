"""Token estimation fallback when the server does not report usage."""
from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token). Clearly an estimate."""
    if not text:
        return 0
    return max(1, len(text) // 4)
