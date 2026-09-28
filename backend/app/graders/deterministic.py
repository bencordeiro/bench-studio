"""Deterministic graders.

Each grader produces a DeterministicGrade-like dict:
  { "passed": bool, "score": float, "max_score": float, "details": dict }

Scores are 0..max_score. The execution engine normalizes to 0..100.
"""
from __future__ import annotations

import json
import re
import string
import unicodedata
from typing import Any

# --------------------------------------------------------------------------- #
# Normalization helpers
# --------------------------------------------------------------------------- #
PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_text(
    text: str,
    *,
    case_sensitive: bool = False,
    trim: bool = True,
    strip_punct: bool = False,
) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    if trim:
        text = text.strip()
        # Collapse internal whitespace.
        text = re.sub(r"\s+", " ", text)
    if not case_sensitive:
        text = text.lower()
    if strip_punct:
        text = text.translate(PUNCT_TABLE).strip()
    return text


# --------------------------------------------------------------------------- #
# Exact / alias match
# --------------------------------------------------------------------------- #
def grade_exact(config: dict, response: str) -> dict[str, Any]:
    canonical = config.get("canonical_answer", "")
    aliases = config.get("accepted_aliases", []) or []
    case_sensitive = bool(config.get("case_sensitive", False))
    trim = bool(config.get("trim_whitespace", True))
    strip_punct = bool(config.get("normalize_punctuation", True))
    points = float(config.get("points", 100.0))

    candidate = _final_answer_line(response)
    norm = normalize_text(
        candidate,
        case_sensitive=case_sensitive,
        trim=trim,
        strip_punct=strip_punct,
    )
    expected_options = [canonical] + list(aliases)
    norm_options = [
        normalize_text(
            o, case_sensitive=case_sensitive, trim=trim, strip_punct=strip_punct
        )
        for o in expected_options
    ]
    passed = any(norm and norm == opt for opt in norm_options if opt)
    # Partial: candidate contains the canonical answer as a distinct token.
    partial = False
    if not passed and canonical:
        words = set(re.findall(r"\w+", norm))
        partial = any(
            normalize_text(
                o, case_sensitive=case_sensitive, trim=trim, strip_punct=strip_punct
            )
            in words
            for o in expected_options
        )
    score = points if passed else (points * 0.4 if partial else 0.0)
    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            "canonical": canonical,
            "aliases": aliases,
            "matched": passed,
            "partial": partial,
            "candidate": candidate,
        },
    }


def _final_answer_line(response: str) -> str:
    """Return the most likely intended answer.

    Prefer a line introduced by an 'answer is:'/'final answer:' style prefix,
    otherwise the last non-empty line. This avoids treating every number in a
    long explanation as the answer.
    """
    if not response:
        return ""
    lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
    if not lines:
        return response.strip()
    # Colon/equals forms: "Answer: X", "Final answer = X"
    answer_re = re.compile(
        r"^(?:final\s*answer|answer|the\s+answer\s+is|a)\s*[:=]\s*(.+)$",
        re.IGNORECASE,
    )
    # Verb forms: "The answer is X", "X is the answer"
    verb_re = re.compile(
        r"^(?:the\s+answer\s+is\s+|answer\s+is\s+)(.+)$",
        re.IGNORECASE,
    )
    for ln in reversed(lines):
        m = answer_re.match(ln)
        if m:
            return m.group(1).strip().strip(".")
        m = verb_re.match(ln)
        if m:
            return m.group(1).strip().strip(".")
    return lines[-1]


# --------------------------------------------------------------------------- #
# Numeric result
# --------------------------------------------------------------------------- #
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def grade_numeric(config: dict, response: str) -> dict[str, Any]:
    expected = float(config["expected_value"])
    abs_tol = float(config.get("absolute_tolerance", 0.0) or 0.0)
    rel_tol = float(config.get("relative_tolerance", 0.0) or 0.0)
    required_unit = (config.get("required_unit") or "").strip()
    unit_aliases = config.get("unit_aliases", []) or []
    points = float(config.get("points", 100.0))

    candidate = _final_answer_line(response)
    value, unit, found = _extract_number(candidate)
    if not found:
        # Fall back to scanning the whole response for the last number.
        value, unit, found = _extract_number(response, prefer_last=True)
    if not found:
        return {
            "passed": False,
            "score": 0.0,
            "max_score": points,
            "details": {"reason": "no numeric value found", "candidate": candidate},
        }
    # Unit check.
    unit_ok = True
    if required_unit:
        accepted_units = {required_unit.lower()} | {u.lower() for u in unit_aliases}
        unit_ok = bool(unit) and unit.lower() in accepted_units
    abs_diff = abs(value - expected)
    within_abs = abs_diff <= abs_tol if abs_tol else False
    within_rel = abs_diff <= rel_tol * abs(expected) if rel_tol and expected != 0 else False
    # Exact match also acceptable.
    exact = abs_diff < 1e-9
    value_ok = exact or within_abs or within_rel
    passed = value_ok and unit_ok
    # Partial credit: value correct but unit wrong (or vice versa).
    score = points if passed else (points * 0.5 if value_ok else 0.0)
    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            "expected": expected,
            "extracted_value": value,
            "extracted_unit": unit,
            "abs_diff": abs_diff,
            "within_tolerance": value_ok,
            "unit_required": required_unit,
            "unit_ok": unit_ok,
            "candidate": candidate,
        },
    }


def _extract_number(text: str, *, prefer_last: bool = False) -> tuple[float | None, str, bool]:
    """Extract a single numeric answer with an optional trailing unit."""
    if not text:
        return None, "", False
    m = _NUM_RE.search(text)
    if not m:
        return None, "", False
    raw = m.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None, "", False
    # Look for a trailing unit immediately after the number.
    tail = text[m.end() :].lstrip()
    unit = ""
    if tail:
        um = re.match(r"([A-Za-z°%²³/]+)", tail)
        if um:
            unit = um.group(1)
    if prefer_last:
        last_val, last_unit, found = value, unit, True
        for nm in _NUM_RE.finditer(text):
            try:
                last_val = float(nm.group(0).replace(",", ""))
            except ValueError:
                continue
            after = text[nm.end() :].lstrip()
            um2 = re.match(r"([A-Za-z°%²³/]+)", after)
            last_unit = um2.group(1) if um2 else ""
        return last_val, last_unit, found
    return value, unit, True


# --------------------------------------------------------------------------- #
# Regular-expression checks
# --------------------------------------------------------------------------- #
def grade_regex(config: dict, response: str) -> dict[str, Any]:
    required = config.get("required_patterns", []) or []
    optional = config.get("optional_patterns", []) or []
    forbidden = config.get("forbidden_patterns", []) or []
    case_sensitive = bool(config.get("case_sensitive", False))
    points = float(config.get("points", 100.0))
    flags = 0 if case_sensitive else re.IGNORECASE

    required_results = []
    required_all_pass = True
    for pat in required:
        try:
            hit = re.search(pat, response, flags) is not None
        except re.error as e:
            hit = False
            required_all_pass = False
            required_results.append({"pattern": pat, "error": str(e)})
            continue
        required_results.append({"pattern": pat, "matched": hit})
        if not hit:
            required_all_pass = False

    optional_results = []
    for pat in optional:
        try:
            optional_results.append(
                {"pattern": pat, "matched": re.search(pat, response, flags) is not None}
            )
        except re.error as e:
            optional_results.append({"pattern": pat, "error": str(e)})

    forbidden_hits = []
    forbidden_violated = False
    for pat in forbidden:
        try:
            m = re.search(pat, response, flags)
        except re.error as e:
            forbidden_hits.append({"pattern": pat, "error": str(e)})
            continue
        if m:
            forbidden_hits.append({"pattern": pat, "matched": True})
            forbidden_violated = True

    if required:
        # Required all pass; forbidden must not appear.
        passed = required_all_pass and not forbidden_violated
        # Score: proportion of required met, halved if forbidden violated.
        met = sum(1 for r in required_results if r.get("matched"))
        ratio = met / len(required)
        if forbidden_violated:
            ratio *= 0.5
        score = points * ratio
    else:
        # No required patterns: pass only if no forbidden hit.
        passed = not forbidden_violated
        score = points if passed else points * 0.25
    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            "required": required_results,
            "optional": optional_results,
            "forbidden": forbidden_hits,
        },
    }


# --------------------------------------------------------------------------- #
# Concept coverage
# --------------------------------------------------------------------------- #
def grade_concept(config: dict, response: str) -> dict[str, Any]:
    required = config.get("required_concepts", []) or []
    optional = config.get("optional_concepts", []) or []
    forbidden = config.get("forbidden_claims", []) or []
    aliases = config.get("aliases", {}) or {}
    points_per = float(config.get("points_per_concept", 10.0))
    cap = float(config.get("cap", 100.0))

    def variants(concept: str) -> list[str]:
        v = [concept]
        v.extend(aliases.get(concept, []))
        return v

    def contains_any(concept_list: list[str]) -> list[tuple[str, bool]]:
        out = []
        for c in concept_list:
            hit = any(v and v.lower() in response.lower() for v in variants(c))
            out.append((c, hit))
        return out

    required_hits = contains_any(required)
    optional_hits = contains_any(optional)
    forbidden_hits = contains_any(forbidden)

    required_met = sum(1 for _, h in required_hits if h)
    optional_met = sum(1 for _, h in optional_hits if h)
    forbidden_count = sum(1 for _, h in forbidden_hits if h)

    # Each required concept is worth points_per; optional worth half.
    earned = required_met * points_per + optional_met * (points_per / 2.0)
    # Forbidden claims subtract.
    earned -= forbidden_count * points_per
    earned = max(0.0, min(earned, cap))

    # Required must all be present (keyword presence alone does not establish
    # correctness, but combined with the cap this signals coverage).
    all_required = required_met == len(required) if required else True
    passed = all_required and forbidden_count == 0
    return {
        "passed": passed,
        "score": earned,
        "max_score": cap,
        "details": {
            "required_concepts": [
                {"concept": c, "matched": h} for c, h in required_hits
            ],
            "optional_concepts": [
                {"concept": c, "matched": h} for c, h in optional_hits
            ],
            "forbidden_claims": [
                {"claim": c, "matched": h} for c, h in forbidden_hits
            ],
            "note": (
                "Concept matching is less reliable than exact/numeric grading; "
                "treat as coverage signal, not proof of correctness."
            ),
        },
    }


# --------------------------------------------------------------------------- #
# Structured JSON
# --------------------------------------------------------------------------- #
def _strict_json_loads(text: str) -> Any:
    def object_pairs(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = value
        return obj

    def invalid_constant(value):
        raise ValueError(f"non-JSON constant: {value}")

    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=invalid_constant)


def grade_json(config: dict, response: str) -> dict[str, Any]:
    require_valid = bool(config.get("require_valid_json", True))
    required_fields = config.get("required_fields", []) or []
    expected_values = config.get("expected_field_values", {}) or {}
    allow_fences = bool(config.get("allow_code_fences", True))
    points = float(config.get("points", 100.0))

    cleaned = response.strip()
    if allow_fences:
        fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fence:
            cleaned = fence.group(1).strip()
    try:
        data = _strict_json_loads(cleaned)
    except ValueError:
        return {
            "passed": False,
            "score": 0.0,
            "max_score": points,
            "details": {"reason": "response is not valid JSON"},
        }
    if require_valid and not isinstance(data, (dict, list)):
        return {
            "passed": False,
            "score": 0.0,
            "max_score": points,
            "details": {"reason": "valid JSON but not an object or array"},
        }
    if (required_fields or expected_values) and not isinstance(data, dict):
        return {"passed": False, "score": 0.0, "max_score": points,
                "details": {"reason": "expected a JSON object"}}
    if config.get("allow_extra_fields") is False and isinstance(data, dict):
        extra = set(data) - set(required_fields) - set(expected_values)
        if extra:
            return {"passed": False, "score": 0.0, "max_score": points,
                    "details": {"unexpected_fields": sorted(extra)}}
    missing = [f for f in required_fields if isinstance(data, dict) and f not in data]
    value_results = []
    value_failures = 0
    if isinstance(data, dict):
        for field, expected in expected_values.items():
            actual = data.get(field)
            ok = field in data and _json_values_match(actual, expected)
            value_results.append({"field": field, "expected": expected, "matched": ok})
            if not ok:
                value_failures += 1
    total_checks = len(required_fields) + len(expected_values)
    if total_checks == 0:
        passed = True
        score = points
    else:
        passed_checks = (len(required_fields) - len(missing)) + (
            len(expected_values) - value_failures
        )
        score = points * (passed_checks / total_checks)
        passed = len(missing) == 0 and value_failures == 0
    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            "missing_fields": missing,
            "field_values": value_results,
            "is_valid_json": True,
        },
    }


def _json_values_match(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _json_values_match(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_values_match(a, e) for a, e in zip(actual, expected))
    return actual == expected



# --------------------------------------------------------------------------- #
# Multiple choice
# --------------------------------------------------------------------------- #
def grade_multiple_choice(config: dict, response: str) -> dict[str, Any]:
    correct = (config.get("correct_option") or "").strip()
    accepted = config.get("accepted_formats", []) or []
    points = float(config.get("points", 100.0))
    candidate = _final_answer_line(response).strip().strip(".").strip(")")
    # Build the accepted set: letter forms + full text.
    accepted_set = {correct}
    for a in accepted:
        if a:
            accepted_set.add(a.strip())
    norm_candidate = candidate.lower()
    norm_accepted = {a.lower() for a in accepted_set if a}
    passed = norm_candidate in norm_accepted or any(
        norm_candidate == a or norm_candidate.startswith(a + " ") or norm_candidate.startswith(a + ")")
        or norm_candidate.startswith(a + ".")
        for a in norm_accepted
    )
    score = points if passed else 0.0
    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            "correct_option": correct,
            "accepted_formats": accepted,
            "candidate": candidate,
        },
    }


# --------------------------------------------------------------------------- #
# Count / length constraints (IFEval-style verifiable instructions)
# --------------------------------------------------------------------------- #
_SENTENCE_RE = re.compile(r"[.!?]+(?=\s|$)")
# A word may carry internal apostrophes, hyphens or decimal points: "doesn't",
# "well-known" and "3.5" are each one word. A bare \b\w+\b splits all three,
# which silently inflates the count -- unfair on a prompt asking for an exact
# number of words, where the model is then failed for writing normal English.
_WORD_RE = re.compile(r"\w+(?:['’.\-]\w+)*")


def grade_count(config: dict, response: str) -> dict[str, Any]:
    """Count occurrences of something and check it against min/max/exact bounds.

    Enables verifiable instruction-following checks such as "exactly 4 bullet
    points", "the word 'data' at most twice", "at least 3 sentences", "under 25
    words". ``unit`` is one of: words, sentences, lines, characters, or (default)
    the number of regex matches of ``pattern``.
    """
    unit = (config.get("unit") or "").lower()
    pattern = config.get("pattern")
    case_sensitive = bool(config.get("case_sensitive", False))
    points = float(config.get("points", 100.0))
    text = response or ""

    if unit == "words":
        n = len(_WORD_RE.findall(text))
    elif unit == "sentences":
        n = len(_SENTENCE_RE.findall(text.strip()))
    elif unit == "lines":
        n = len([ln for ln in text.splitlines() if ln.strip()])
    elif unit == "characters":
        n = len(text)
    else:
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            n = len(re.findall(pattern or "", text, flags))
        except re.error as e:
            return {"passed": False, "score": 0.0, "max_score": points,
                    "details": {"error": f"invalid pattern: {e}"}}

    exact = config.get("exact")
    min_count = config.get("min")
    max_count = config.get("max")
    passed = True
    if exact is not None:
        passed = n == int(exact)
    else:
        if min_count is not None and n < int(min_count):
            passed = False
        if max_count is not None and n > int(max_count):
            passed = False
    return {
        "passed": passed,
        "score": points if passed else 0.0,
        "max_score": points,
        "details": {"count": n, "unit": unit or "matches", "pattern": pattern,
                    "min": min_count, "max": max_count, "exact": exact},
    }


# --------------------------------------------------------------------------- #
# Tool calls (Hermes / BFCL-style function calling)
# --------------------------------------------------------------------------- #
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL | re.IGNORECASE)


def parse_tool_calls(response: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract Hermes ``<tool_call>`` blocks as parsed JSON objects.

    Returns ``(calls, malformed)``. A block whose payload is not a JSON object
    lands in ``malformed`` rather than being silently ignored -- emitting a
    broken call is a failure mode worth scoring, not overlooking.
    """
    calls: list[dict[str, Any]] = []
    malformed: list[str] = []
    for raw in _TOOL_CALL_RE.findall(response or ""):
        payload = raw.strip()
        if payload.startswith("```"):
            payload = re.sub(r"^```(?:json)?\s*|\s*```$", "", payload).strip()
        try:
            obj = _strict_json_loads(payload)
        except ValueError:
            malformed.append(payload[:200])
            continue
        if isinstance(obj, list):
            for item in obj:
                (calls if isinstance(item, dict) else malformed).append(
                    item if isinstance(item, dict) else str(item)[:200]
                )
        elif isinstance(obj, dict):
            calls.append(obj)
        else:
            malformed.append(payload[:200])
    return calls, malformed


def _arg_values_match(actual: Any, expected: Any) -> bool:
    """Compare one argument value, tolerating 4 vs "4" and case/space drift.

    ``expected`` may be ``{"any_of": [...]}`` to declare genuinely equivalent
    forms. Some arguments have more than one correct spelling -- an ISO
    timestamp is as valid with seconds as without -- and failing a model for
    picking the other one measures luck, not capability.
    """
    if isinstance(expected, dict) and "any_of" in expected:
        return any(_arg_values_match(actual, alt) for alt in expected["any_of"])
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) < 1e-9
    if isinstance(expected, list) and isinstance(actual, list):
        # Order-sensitive, but each element gets the same tolerant comparison.
        return len(actual) == len(expected) and all(
            _arg_values_match(a, e) for a, e in zip(actual, expected)
        )
    if isinstance(expected, (list, dict)) or isinstance(actual, (list, dict)):
        return actual == expected
    return str(actual).strip().lower() == str(expected).strip().lower()


def _strict_arg_match(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and set(expected) == {"any_of"}:
        return any(_strict_arg_match(actual, alt) for alt in expected["any_of"])
    return _json_values_match(actual, expected)


def _call_matches(call: dict, spec: dict, *, strict_args: bool, strict_types: bool = False) -> tuple[bool, dict]:
    """Does one emitted call satisfy one expected-call spec?"""
    detail: dict[str, Any] = {"expected_name": spec.get("name")}
    name_ok = str(call.get("name", "")).strip().lower() == str(spec.get("name", "")).strip().lower()
    if strict_types:
        name_ok = call.get("name") == spec.get("name")
    detail["name_ok"] = name_ok
    if not name_ok:
        return False, detail

    args = call.get("arguments")
    if not isinstance(args, dict):
        args = call.get("parameters") if isinstance(call.get("parameters"), dict) else {}
    expected_args = spec.get("arguments", {}) or {}

    arg_details = []
    all_args_ok = True
    for key, want in expected_args.items():
        present = key in args
        ok = present and (_strict_arg_match(args[key], want) if strict_types else _arg_values_match(args[key], want))
        arg_details.append(
            {"arg": key, "expected": want, "actual": args.get(key), "matched": ok}
        )
        if not ok:
            all_args_ok = False
    detail["arguments"] = arg_details

    if strict_args:
        extra = sorted(set(args) - set(expected_args))
        detail["unexpected_arguments"] = extra
        if extra:
            all_args_ok = False

    forbidden_args = spec.get("forbidden_arguments", []) or []
    present_forbidden = [a for a in forbidden_args if a in args]
    if present_forbidden:
        detail["forbidden_arguments_present"] = present_forbidden
        all_args_ok = False

    return all_args_ok, detail


def grade_tool_call(config: dict, response: str) -> dict[str, Any]:
    """Grade function-calling output by parsing each call, not by regex.

    A regex over the whole response cannot bind an argument to the call it
    belongs to -- ``"unit": "celsius"`` on call #1 would satisfy a check meant
    for call #2. This parses every ``<tool_call>`` block and matches expected
    calls against emitted ones individually, so a correct tool name with wrong
    arguments fails.

    config keys:
      expected_calls    list of {name, arguments, forbidden_arguments}
      expect_no_calls   True for relevance items -- any call is a failure
      allow_extra_calls tolerate calls beyond those expected (default False)
      strict_args       reject arguments not named in the spec (default False)
      forbidden_names   tool names that must never appear
    """
    points = float(config.get("points", 100.0))
    expected = config.get("expected_calls", []) or []
    expect_none = bool(config.get("expect_no_calls", False))
    allow_extra = bool(config.get("allow_extra_calls", False))
    strict_args = bool(config.get("strict_args", False))
    forbidden_names = [n.lower() for n in (config.get("forbidden_names", []) or [])]

    calls, malformed = parse_tool_calls(response)
    if config.get("strict_format"):
        blocks = _TOOL_CALL_RE.findall(response or "")
        residue = _TOOL_CALL_RE.sub("", response or "").strip()
        invalid = bool(residue) if not expect_none else bool(re.search(r"</?tool_call\b", response, re.I))
        for raw in blocks:
            try:
                obj = _strict_json_loads(raw)
                invalid |= (not isinstance(obj, dict) or set(obj) != {"name", "arguments"}
                            or not isinstance(obj.get("arguments"), dict))
            except (ValueError, AttributeError):
                invalid = True
        if invalid:
            return {"passed": False, "score": 0.0, "max_score": points,
                    "details": {"reason": "invalid Hermes envelope or extra text"}}
    base_details = {
        "calls_found": len(calls),
        "call_names": [str(c.get("name", "")) for c in calls],
        "malformed_blocks": malformed,
    }

    if expect_none:
        passed = not calls and not malformed
        return {
            "passed": passed,
            "score": points if passed else 0.0,
            "max_score": points,
            "details": {**base_details, "expected": "no tool calls"},
        }

    if not expected:
        passed = bool(calls) and not malformed
        return {
            "passed": passed,
            "score": points if passed else 0.0,
            "max_score": points,
            "details": {**base_details, "expected": "at least one well-formed call"},
        }

    unmatched = list(range(len(calls)))
    match_details = []
    matched_count = 0
    for spec in expected:
        best_idx = None
        best_detail = None
        for idx in unmatched:
            ok, detail = _call_matches(calls[idx], spec, strict_args=strict_args, strict_types=bool(config.get("strict_types")))
            if ok:
                best_idx, best_detail = idx, detail
                break
            # Remember a same-name near miss so the report shows why it failed.
            if detail.get("name_ok") and best_detail is None:
                best_detail = detail
        if best_idx is not None:
            unmatched.remove(best_idx)
            matched_count += 1
            match_details.append({"matched": True, **(best_detail or {})})
        else:
            match_details.append(
                {"matched": False, **(best_detail or {"expected_name": spec.get("name"),
                                                     "name_ok": False})}
            )

    extra_calls = [calls[i] for i in unmatched]
    bad_names = [n for n in base_details["call_names"] if n.lower() in forbidden_names]

    # Each spurious call, malformed block, or forbidden name burns one slot.
    penalty = len(malformed) + len(bad_names)
    if not allow_extra:
        penalty += len(extra_calls)
    effective = max(0, matched_count - penalty)
    score = points * (effective / len(expected))
    passed = matched_count == len(expected) and penalty == 0

    return {
        "passed": passed,
        "score": score,
        "max_score": points,
        "details": {
            **base_details,
            "expected_count": len(expected),
            "matched_count": matched_count,
            "extra_calls": [str(c.get("name", "")) for c in extra_calls],
            "forbidden_names_used": bad_names,
            "checks": match_details,
        },
    }


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
GRADER_FUNCS = {
    "exact": grade_exact,
    "numeric": grade_numeric,
    "regex": grade_regex,
    "concept": grade_concept,
    "json": grade_json,
    "multiple_choice": grade_multiple_choice,
    "count": grade_count,
    "tool_call": grade_tool_call,
}


def run_deterministic(config: dict, response: str) -> dict[str, Any]:
    """Run a single deterministic check given its config dict.

    A deterministic prompt may combine multiple checks. ``config`` may be a
    single check dict (with a ``type``) or a list under ``checks``.
    """
    checks = config.get("checks") if isinstance(config, dict) else None
    if not checks:
        if isinstance(config, dict) and "type" in config:
            checks = [config]
        else:
            checks = []
    results = []
    total_score = 0.0
    total_max = 0.0
    all_passed = True
    gate_failed = False
    for chk in checks:
        ctype = chk.get("type", "exact")
        func = GRADER_FUNCS.get(ctype, grade_exact)
        # Prose checks on a relevance item must not be satisfied by the tool-call
        # JSON itself -- a hallucinated {"destination": "New York"} would otherwise
        # supply the very keyword the check is looking for.
        subject = response
        if chk.get("strip_tool_calls"):
            subject = _TOOL_CALL_RE.sub(" ", response or "").strip()
        try:
            r = func(chk, subject)
        except Exception as e:
            r = {
                "passed": False,
                "score": 0.0,
                "max_score": float(chk.get("points", 100.0)),
                "details": {"error": f"{ctype} grader failed: {e}"},
            }
        r["type"] = ctype
        if chk.get("gate"):
            r["gate"] = True
            if not r["passed"]:
                gate_failed = True
        results.append(r)
        total_score += r["score"]
        total_max += r["max_score"]
        if not r["passed"]:
            all_passed = False
    if total_max == 0:
        total_max = 100.0
    # Combined score is the average fraction across the SCORED checks * 100.
    # A gate is a precondition, not an achievement: clearing it earns nothing,
    # it only buys the right to be scored on the real constraints. Counting it
    # paid out for "- a / - b / - c" on a three-bullet prompt.
    scored = [r for r in results if not r.get("gate")] or results
    if scored:
        fractions = [r["score"] / r["max_score"] if r["max_score"] else 0.0 for r in scored]
        normalized = (sum(fractions) / len(fractions)) * 100.0
    else:
        normalized = 0.0
    # A failed gate zeroes the item. Without this, prompts built from negative
    # constraints ("do not use the letter 'e'", "avoid these words") pay out for
    # saying nothing at all -- an empty response satisfies every prohibition and
    # scored 67 on the lipogram item. The gate is the check that proves the
    # model actually attempted the task.
    if gate_failed:
        normalized = 0.0
        total_score = 0.0
        all_passed = False
    return {
        "passed": all_passed,
        "score": round(normalized, 4),
        "max_score": 100.0,
        "raw_points": round(total_score, 4),
        "raw_max": round(total_max, 4),
        "gate_failed": gate_failed,
        "checks": results,
    }
