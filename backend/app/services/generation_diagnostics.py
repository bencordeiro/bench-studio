"""Observational generation diagnostics; never interrupt or change model output."""
from __future__ import annotations

from collections import Counter


def generation_diagnostics(content: str, reasoning: str, finish_reason: str) -> dict:
    # Inspect a bounded tail so diagnostics stay inexpensive on long streams.
    # Repeated long line prefixes catch both verbatim loops and escalating
    # hypothetical cases. This is a warning heuristic, not proof of a loop.
    prefixes = [line.strip()[:80] for line in (reasoning or content)[-32000:].splitlines()
                if len(line.strip()) >= 20]
    repeated = max(Counter(prefixes).values(), default=0)
    return {
        "answer_chars": len(content),
        "reasoning_chars": len(reasoning),
        "no_final_answer": not bool(content.strip()),
        "possible_repetition": repeated >= 10,
        "repeated_line_prefix_count": repeated,
        "truncated": finish_reason == "length",
    }
