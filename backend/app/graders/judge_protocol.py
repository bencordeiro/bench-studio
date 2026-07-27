"""LLM judge prompt construction and output validation."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError


# --------------------------------------------------------------------------- #
# Strict output schema
# --------------------------------------------------------------------------- #
class DimensionScore(BaseModel):
    score: float = Field(..., ge=0)
    maximum: float = Field(..., gt=0)
    reason: str = ""


class JudgeOutput(BaseModel):
    """The strict JSON schema a judge must return."""
    dimension_scores: dict[str, DimensionScore]
    raw_total: float = Field(..., ge=0)
    critical_error: bool = False
    score_cap: float | None = None
    final_score: float = Field(..., ge=0, le=100)
    confidence: float = Field(..., ge=0, le=1)
    strengths: list[str] = Field(default_factory=list)
    deductions: list[dict] = Field(default_factory=list)


class VerifierOutput(BaseModel):
    confirmed: bool
    verified_score: float = Field(..., ge=0, le=100)
    adjusted: bool = False
    adjustment_reason: str = ""
    confidence: float = Field(..., ge=0, le=1)
    problems_found: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = (
    "You are a strict, impartial evaluator for an LLM benchmark. You evaluate "
    "the quality of a candidate answer against a rubric. You do not know the "
    "identity of the model that produced the answer.\n\n"
    "Principles:\n"
    "- Evaluate correctness, not similarity of wording.\n"
    "- Alternative correct approaches are allowed.\n"
    "- Do not reward verbosity by itself.\n"
    "- Do not penalize concise answers that fully satisfy the task.\n"
    "- Do not assume unstated reasoning.\n"
    "- Support every deduction with concrete candidate evidence.\n"
    "- Apply critical-error caps consistently.\n"
    "- Treat the reference answer as guidance, not the only valid answer.\n"
    "- Return ONLY the required JSON. No prose before or after."
)


def _format_rubric(config: dict) -> str:
    dims = config.get("rubric_dimensions", []) or []
    lines = []
    for d in dims:
        lines.append(
            f"- {d.get('name', 'dimension')} (max {d.get('maximum', 100)}, weight {d.get('weight', 1)}): "
            f"{d.get('description', '')}"
        )
    rubric_text = "\n".join(lines) if lines else "(no dimensions specified)"
    required = config.get("required_elements", []) or []
    critical = config.get("critical_errors", []) or []
    caps = config.get("score_caps", []) or []
    return (
        f"Rubric dimensions:\n{rubric_text}\n\n"
        f"Required elements: {json.dumps(required)}\n\n"
        f"Critical errors (any present => critical_error=true): {json.dumps(critical)}\n\n"
        f"Score caps: {json.dumps(caps)}"
    )


def build_judge_messages(
    *,
    original_messages: list[dict],
    candidate_response: str,
    config: dict,
    extra_instructions: str = "",
) -> list[dict]:
    """Build the message array sent to the judge model."""
    user_prompt = (
        "Evaluate the following candidate answer.\n\n"
        f"Original task messages:\n{json.dumps(original_messages, indent=2)}\n\n"
        f"Candidate response:\n---\n{candidate_response}\n---\n\n"
        f"{_format_rubric(config)}\n\n"
        f"Reference answer (guidance only, not required wording):\n{config.get('reference_answer', '')}\n\n"
        f"Reference facts: {json.dumps(config.get('reference_facts', []))}\n\n"
    )
    if config.get("strong_example"):
        user_prompt += f"Example strong answer:\n{config['strong_example']}\n\n"
    if config.get("weak_example"):
        user_prompt += f"Example weak answer:\n{config['weak_example']}\n\n"
    if extra_instructions:
        user_prompt += f"Additional judge instructions:\n{extra_instructions}\n\n"
    user_prompt += (
        "Return JSON ONLY in this exact shape:\n"
        "{\n"
        '  "dimension_scores": { "<name>": {"score": number, "maximum": number, "reason": "..." } },\n'
        '  "raw_total": number,\n'
        '  "critical_error": boolean,\n'
        '  "score_cap": number | null,\n'
        '  "final_score": number,\n'
        '  "confidence": number,\n'
        '  "strengths": ["..."],\n'
        '  "deductions": [{"points": number, "reason": "...", "candidate_evidence": "..."}]\n'
        "}\n"
        "final_score MUST be between 0 and 100 inclusive and reflect any score cap applied."
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def build_verifier_messages(
    *,
    original_messages: list[dict],
    candidate_response: str,
    config: dict,
    judge_result: dict,
) -> list[dict]:
    user_prompt = (
        "You are verifying a previous judge decision for an LLM benchmark answer.\n\n"
        "Check:\n"
        "- Were factual errors missed?\n"
        "- Are deductions supported by candidate evidence?\n"
        "- Was verbosity rewarded?\n"
        "- Was an alternative valid approach unfairly penalized?\n"
        "- Does the numerical score match the written analysis?\n"
        "- Were score caps applied correctly?\n\n"
        f"Original task messages:\n{json.dumps(original_messages, indent=2)}\n\n"
        f"Candidate response:\n---\n{candidate_response}\n---\n\n"
        f"Rubric & reference:\n{_format_rubric(config)}\n\n"
        f"Reference answer:\n{config.get('reference_answer', '')}\n\n"
        f"Initial judge result:\n{json.dumps(judge_result, indent=2)}\n\n"
        "Return JSON ONLY in this exact shape:\n"
        "{\n"
        '  "confirmed": boolean,\n'
        '  "verified_score": number,\n'
        '  "adjusted": boolean,\n'
        '  "adjustment_reason": "...",\n'
        '  "confidence": number,\n'
        '  "problems_found": ["..."]\n'
        "}\n"
        "If the original judgment is correct, confirmed=true and verified_score equals the original. "
        "Do not average arbitrary scores; only adjust when there is a concrete, evidenced problem."
    )
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]


def build_repair_message(validation_error: str) -> dict:
    return {
        "role": "user",
        "content": (
            "Your previous response was invalid and could not be parsed. "
            "Return ONLY valid JSON matching the schema. Validation error:\n"
            f"{validation_error}\n\n"
            "Try again, returning the JSON object only."
        ),
    }


# --------------------------------------------------------------------------- #
# Output parsing
# --------------------------------------------------------------------------- #
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_json_object(text: str) -> str:
    """Pull the first balanced {...} substring from text."""
    text = _strip_fences(text)
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def parse_judge_output(raw: str) -> tuple[JudgeOutput | None, str]:
    """Parse and validate judge output. Returns (model_or_None, error_message)."""
    if not raw:
        return None, "empty judge response"
    candidate = _extract_json_object(raw)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    # Normalize dimension_scores values.
    if isinstance(data.get("dimension_scores"), dict):
        norm = {}
        for k, v in data["dimension_scores"].items():
            if isinstance(v, dict):
                norm[k] = v
            elif isinstance(v, (int, float)):
                norm[k] = {"score": float(v), "maximum": 100.0, "reason": ""}
        data["dimension_scores"] = norm
    # Coerce booleans/numbers that may arrive as strings.
    for bool_key in ("critical_error",):
        if bool_key in data and isinstance(data[bool_key], str):
            data[bool_key] = data[bool_key].lower() in {"true", "1", "yes"}
    try:
        return JudgeOutput.model_validate(data), ""
    except ValidationError as e:
        return None, f"schema validation failed: {e}"


def parse_verifier_output(raw: str) -> tuple[VerifierOutput | None, str]:
    if not raw:
        return None, "empty verifier response"
    candidate = _extract_json_object(raw)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    for bool_key in ("confirmed", "adjusted"):
        if bool_key in data and isinstance(data[bool_key], str):
            data[bool_key] = data[bool_key].lower() in {"true", "1", "yes"}
    try:
        return VerifierOutput.model_validate(data), ""
    except ValidationError as e:
        return None, f"schema validation failed: {e}"


def judge_output_to_dict(out: JudgeOutput) -> dict[str, Any]:
    return {
        "dimension_scores": {k: v.model_dump() for k, v in out.dimension_scores.items()},
        "raw_total": out.raw_total,
        "critical_error": out.critical_error,
        "score_cap": out.score_cap,
        "final_score": out.final_score,
        "confidence": out.confidence,
        "strengths": out.strengths,
        "deductions": out.deductions,
    }
