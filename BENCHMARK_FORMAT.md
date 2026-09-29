# Benchmark Format

The benchmark-set import/export format is a versioned JSON document — the same format used for every bundled suite, including **Terminal Semantics & System Gotchas**. Top-level shape:

```json
{
  "format": "localbench-benchmark",
  "format_version": "1.0",
  "exported_at": "2026-07-16T14:00:00+00:00",
  "name": "My Benchmark",
  "description": "...",
  "version": "1.0.0",
  "tags": ["math", "reasoning"],
  "scoring_config": {},
  "performance_thresholds": {
    "desired_ttft": 0.5,
    "max_ttft": 5.0,
    "desired_tps": 40.0,
    "min_tps": 5.0,
    "max_failure_rate": 0.1
  },
  "composite_weights": { "quality": 0.85, "reliability": 0.10, "performance": 0.05 },
  "prompts": [ { ... } ]
}
```

## Prompt object

```json
{
  "stable_id": "math-area",
  "title": "Circle area",
  "description": "Numeric answer with tolerance",
  "category": "math",
  "tags": ["numeric"],
  "difficulty": "medium",
  "importance_weight": 1.5,
  "position": 0,
  "enabled": true,
  "grading_mode": "deterministic",
  "generation_overrides": { "temperature": 0.0 },
  "grader_config": { ... },
  "messages": [
    { "role": "user", "content": "Compute the area of a circle with radius 10.", "position": 0 }
  ]
}
```

`grading_mode` is one of `deterministic`, `judge`, `hybrid`, `manual`, `execution`.

`generation_overrides` may include `temperature`, `top_p`, `stop`, `seed`, and
`reasoning_effort` (`low`/`medium`/`high`/`xhigh`, sent as
`chat_template_kwargs.reasoning_effort` for llama.cpp / LM Studio). **Never set
`max_tokens` here** — a per-prompt cap truncates a chain-of-thought model before
its answer lands. The run config owns the token budget: `max_tokens: 0` (the
default) means "server default / no cap", and only a positive run-level value
caps output.

## Grader configs

### Deterministic (`grading_mode: "deterministic"`)

A single check has a `type`. A prompt may also combine checks under `checks: [...]`.

- **exact** — `{ "type": "exact", "canonical_answer": "Paris", "accepted_aliases": ["..."], "case_sensitive": false, "trim_whitespace": true, "normalize_punctuation": true, "points": 100 }`
- **numeric** — `{ "type": "numeric", "expected_value": 314.16, "absolute_tolerance": 0.5, "relative_tolerance": 0.0, "required_unit": "cm²", "unit_aliases": ["cm2"], "points": 100 }`
- **regex** — `{ "type": "regex", "required_patterns": ["\\berror\\b"], "optional_patterns": [], "forbidden_patterns": ["rm -rf"], "case_sensitive": false, "points": 100 }`
- **concept** — `{ "type": "concept", "required_concepts": ["encryption"], "optional_concepts": [], "forbidden_claims": ["HTTP is secure by default"], "aliases": { "TLS": ["SSL"] }, "points_per_concept": 20.0, "cap": 100.0 }`
- **json** — `{ "type": "json", "require_valid_json": true, "required_fields": ["name","age"], "expected_field_values": { "age": 34 }, "allow_code_fences": true, "points": 100 }`
- **multiple_choice** — `{ "type": "multiple_choice", "correct_option": "B", "accepted_formats": ["Option B", "Ottawa"], "points": 100 }`
- **count** — verifiable-instruction counting (IFEval-style). Counts a `unit` (`words`, `sentences`, `lines`, `characters`) or, by default, regex matches of `pattern`, and checks it against `exact`, `min`, and/or `max`. `{ "type": "count", "unit": "words", "min": 20, "max": 40, "points": 100 }` or `{ "type": "count", "pattern": "(?m)^- ", "exact": 3, "points": 100 }`. Combine several under `checks` to stack constraints in one prompt.
- **tool_call** — function-calling output, parsed rather than pattern-matched. Each `<tool_call>` block is decoded as JSON and matched against `expected_calls` individually, so a correct tool name with fabricated arguments fails. `{ "type": "tool_call", "expected_calls": [{ "name": "get_weather", "arguments": { "location": "Paris", "unit": "celsius" } }], "strict_args": true, "forbidden_names": ["send_email"], "points": 100 }`. Use `expect_no_calls: true` for relevance items (the model should answer in prose instead), `allow_extra_calls` to tolerate additional calls, and `strict_args` to reject arguments not named in the spec. A malformed `<tool_call>` block counts against the score — real agent harnesses cannot parse it either.

#### Check modifiers

- **`gate: true`** — if this check fails, the whole prompt scores **0** regardless of the other checks.

  Required on any prompt built from prohibitions. "Do not use the letter 'e'", "avoid these words" and "do not use digits" are all satisfied by an empty response, so without a gate an item pays out for saying nothing — the lipogram prompt scored 67 for silence. Make the gate the check that proves the model attempted the task (a word floor, the required section headers, the concept it was asked about).

  Keep gates loose enough that only a non-attempt trips them. A gate is an anti-refusal floor, not a hidden length requirement: gating the exchange-rate prompt at 40 words would zero a correct one-sentence answer.

- **`strip_tool_calls: true`** — evaluate this check against the response with `<tool_call>` blocks removed. Stops a hallucinated call from supplying the very keyword a prose check is looking for.

- **`{ "any_of": [...] }`** as an expected argument value in `tool_call` — accepts several genuinely equivalent forms. `"start": { "any_of": ["2026-03-09T14:00", "2026-03-09T14:00:00"] }`. Use it wherever more than one answer is correct; failing a model for picking the other valid spelling measures luck, not capability.

### Judge (`grading_mode: "judge"`)

```json
{
  "reference_answer": "...",
  "reference_facts": ["..."],
  "required_elements": ["..."],
  "rubric_dimensions": [
    { "name": "correctness", "description": "...", "weight": 2.0, "maximum": 40 }
  ],
  "critical_errors": ["recommends disabling all security"],
  "score_caps": [],
  "judge_instructions": "...",
  "strong_example": "...",
  "weak_example": "..."
}
```

The judge returns strict JSON matching the schema in `app/graders/judge_protocol.py` (`JudgeOutput`).

### Hybrid (`grading_mode: "hybrid"`)

```json
{
  "deterministic_checks": [ { "type": "regex", "forbidden_patterns": ["rm -rf /"], "points": 100 } ],
  "deterministic_weight": 40.0,
  "judge_weight": 60.0,
  "judge": { ...same shape as a judge config... },
  "critical_fail_caps": [ { "applies_when": "destructive_command", "cap": 20 } ]
}
```

`deterministic_weight + judge_weight` must equal 100.

### Manual (`grading_mode: "manual"`)

`grader_config` is empty; the prompt is captured for human review.

### Execution (`grading_mode: "execution"`)

Functional correctness for code-completion prompts, graded the way the
HumanEval reference harness (openai/human-eval, MIT) does it:

```json
{
  "language": "python",
  "test_code": "def check(candidate):\n    assert candidate(1) == 2",
  "entry_point": "add_one",
  "timeout_seconds": 3.0
}
```

- `completion_mode` defaults to `"body"`, preserving the reference completion contract. Set it to `"full_function"` when the model must return a complete raw function definition; in this mode the user message is an instruction, and only the response is executed before the tests. Neither mode strips fences or repairs indentation.
- In body mode, the program `prompt + completion + "\n" + test_code + "\n" + check(entry_point)` is executed in a fresh `python -I` subprocess (throwaway cwd, stdin closed) with a wall-clock `timeout_seconds` (default 3.0, the reference harness's default).
- The **prompt text is not stored in `grader_config`** — it is the prompt's user message(s), which keeps `grader_config` ASCII-clean for prompts whose docstrings contain unicode.
- The completion is used exactly as produced: no markdown-fence stripping, no repair. A fenced reply is a SyntaxError, exactly as under the reference harness.
- The child applies a reliability guard (adapted from the reference harness, MIT) that removes destructive builtins before the program runs. It is a guard, not a sandbox.
- Result: **100** if the program completes cleanly, **0** otherwise. `details.status` is `passed`, `timed out`, or `failed: ...` — the reference harness's three classifications. No partial credit, so a suite's unweighted pass rate is standard pass@1.

## Validation on import

Imports are validated against these schemas. A corrupt or partially-invalid file is **rejected entirely** with a clear error — it is never partially imported. No file may contain secrets; exports never include API keys.

### Strict structured-output options

JSON checks accept `allow_extra_fields: false` to reject object keys outside
`required_fields` and `expected_field_values`. Set `allow_code_fences: false` for
raw JSON-only tasks. Field comparisons are recursive, order-independent for
object keys, order-sensitive for arrays, and distinguish booleans from numbers.
Duplicate keys and non-finite constants (`NaN`, `Infinity`) are rejected.

Tool-call checks accept `strict_format: true` for exactly one object per Hermes
block with only `name` and object-valued `arguments`, and no surrounding prose.
`strict_types: true` preserves string casing and numeric types instead of using
legacy coercion. `strict_args: true` rejects extra arguments. Explicit
`{"any_of": [...]}` values can express equivalent timestamp forms or numeric
representations. These strict options are opt-in for imported suites.
