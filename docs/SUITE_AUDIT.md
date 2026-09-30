# Curated suite audit — September 2026

This revision contains 225 custom prompts, plus the unchanged 164-question
HumanEval suite (389 total). Mini Master intentionally overlaps with Master.
It emphasizes clear contracts and reproducible
scoring. Difficulty is a design judgment until measured against models. The
Qwen Flash duration observations are documented separately; Cyber was validated
offline. No cross-model difficulty calibration has been completed.

| Suite | Before → after | Version | Changes |
|---|---:|---|---|
| Instruction-Following & Format Adherence | 12 → 15 | 6.0.0 | Reviewed all constraints; added untrusted-data extraction, CSV escaping, conditional redaction |
| Agentic Tool-Use & Structured Output (Hermes) | 14 → 15 | 4.0.0 | Exact envelopes and types; harder argument derivation, cross-year dates, filtered fan-out, retry state |
| Master Suite | 56 → 45 | 5.0.0 | Additional five duration-driven removals; concise final answers and disclosed numeric tolerances |
| Mini Master | 0 → 25 | 1.0.0 | 13 selected Master items plus 12 compact variants; class-scope/comprehension item excluded |
| Cyber | 0 → 18 | 1.0.0 | Original defensive-security scenarios, closed JSON schemas, independent answer and error controls |
| Terminal Semantics & System Gotchas | 12 → 12 | 2.0.0 | Corrected three bad keys; revised four shallow items; specified environment assumptions |
| Web Dev Correctness & Debugging (JS) | 46 → 45 | 5.0.0 | Removed `wd-typeof-null`; reproduced every remaining output |
| Code Reasoning & Correctness (Python) | 55 → 50 | 6.0.0 | Retained 30 reasoning items; replaced 25 with 20 original complete-function execution tasks |

## Instruction following

All 15 items have a compliant-response control. Regressions cover incorrect
casing, misplaced delimiters, blank acrostic lines, broken CSV quoting, missing
placeholders, repeated keywords concentrated in one sentence, and leaking
redacted data. Fixes include:

- JSON-only means raw JSON, without fences or extra keys. Arrays no longer pass
  object-field checks; nested objects compare independently of key order.
- Boolean values cannot pass as integers. Missing fields cannot masquerade as null.
- Placeholder regexes were overescaped and could reject normal `[date]` syntax.
- The postscript task now specifies a clear three-line contract, avoiding the
  ambiguity of counting periods in `P.S.` as separate sentences.
- Titles must start the response; the delimiter task enforces the entire shape.
- A ROUTINE must appear in every sentence, not merely three times somewhere.

Free-form prose tasks measure verifiable constraints and topic signals, not
literary quality or a complete semantic proof of factual accuracy.

## Hermes

The suite tests **textual Hermes output**, not native API `tool_calls` or a live
autonomous agent loop. Calls are parsed and bound to their own arguments; extra
calls lose credit. Strict mode rejects surrounding text, malformed/unclosed
blocks, arrays packed into one block, alternate field names, and wrong types.
String casing is preserved. Explicit alternatives cover equivalent timestamp
spellings, attendee order, and JSON number representations where appropriate.

The revised hotel request crosses a year boundary; restaurant headcount includes
a cancellation and midnight conversion; stock requests require filtering and
deduplication. Literal translation text must not become another conversion call.
The new retry carries nested items and the original idempotency key across an
error, while ignoring instructions embedded in an untrusted result. Creative
relevance now asks for three lines rather than an ungraded haiku syllable count.
Every item has a positive control and a spurious-call negative control.

## Python

The 30 retained output tasks cover aliasing, closures, exception behavior,
iterators, generators, descriptors, inheritance, and data aggregation. All
canonical outputs are reproduced by executing their actual prompt snippets.
The exact retained IDs live in `scripts/build_python_suite.py`.

The 20 new tasks use HumanEval's short function-contract/completion approach,
with original scenarios and tests (no copied HumanEval questions):

| Function | Main failure modes checked |
|---|---|
| `merge_windows` | Touching/nested intervals, duplicates, negative bounds |
| `latest_records` | Timestamp ties, first-ID order, older later arrivals |
| `dependency_batches` | Duplicate edges, cycles, partial acyclic components |
| `resolve_path` | Above-root traversal, repeated slashes, literal dot names |
| `apply_patch` | Nested deletion, replacement of scalars, falsey values |
| `inventory_ledger` | Global event-ID deduplication, zero/negative balances |
| `rolling_totals` | Open left boundary, repeated timestamps, negative values |
| `retry_delays` | Cap below initial delay, exact budget, factor one |
| `parse_query` | Repeated/blank keys, encoded plus, embedded equals, Unicode |
| `diff_records` | Missing versus null, order-independent records |
| `allocate_cents` | Remainder ties, zero weights, integers beyond float precision |
| `longest_streak` | Duplicates, negative days, deterministic tie breaking |
| `flatten_records` | Empty nested dicts and lists treated as leaves |
| `missing_ranges` | Huge domains, duplicates, out-of-range IDs |
| `lru_misses` | Refresh on hits, zero capacity, final recency order |
| `sessionize` | Exact timeout boundary, duplicate timestamps |
| `expand_template` | Unknown/malformed placeholders, one-pass expansion |
| `match_route` | Full match, empty captures, literal casing, root |
| `first_conflict` | Half-open intervals, zero length, lexicographic index priority |
| `paginate` | Missing cursor, strict boundary, exact final page |

Each task tests unchanged inputs and multiple calls to the same implementation.
Reference bodies remain in `scripts/python_tasks.py`; they are not sent to the
model. Empty and constant-return implementations fail. Reference implementations
run through the same execution grader used for model responses. The suite is a
weighted mix of reasoning and coding, not HumanEval pass@1. Execution uses the
existing subprocess reliability guard, with the limitations documented in README.

## Terminal

Every question has an independent validation in `test_terminal_answers.py`.
No privileged firewall changes or real package installations are needed.

| ID | Review result / expected answer |
|---|---|
| `ts-perm-mask` | Mask union then chmod restriction: `770,754,r-x`; explicitly assumes ACL support |
| `ts-git-forensics` | Rewritten: divergent history and saved tag, `3,3,1` |
| `ts-date-normalization` | Verified epoch/UTC order; offsets explicitly supplied |
| `ts-log-aggregation` | Recounted normalized log addresses: `203.0.113.4 11` |
| `ts-html-sed` | Actual GNU sed range prints 13 lines |
| `ts-sqlite-wal` | Rewritten: reader snapshot across another connection's commit, `10,10,30` |
| `ts-cron-firing` | Rewritten: restricted day fields use OR, 24 firings |
| `ts-bash-pipefail` | Rewritten: capture status and PIPESTATUS together, `3\|7 3 0` |
| `ts-conda-conflict` | Corrected B → C; scipy 1.11 satisfies both dataforge and numpy constraints |
| `ts-sort-locale` | Verified C locale order; literal quoting/no aliases specified |
| `ts-find-xargs` | Corrected 3 → 4: whitespace does not prevent quoted `*.txt` matching |
| `ts-iptables-filter` | Corrected `2,4,6` → `1,2,3,4,5,6`; every packet hits an ACCEPT rule |

ACL integration is conditional on filesystem support and skips when named ACL
writes are unsupported. A separate bitmask-rule test always validates the key
against the upstream
[setfacl manual](https://man7.org/linux/man-pages/man1/setfacl.1.html) and
[ACL/chmod correspondence](https://man7.org/linux/man-pages/man5/acl.5.html).

## Master and Webdev selection

Master removals are qualitative choices, not observed model failure rankings:
`ms-auto-injector-pulse-width` is unit conversion plus an offset;
`ms-auto-can-clock-tolerance` supplies both formulas and asks for their minimum.
Their extreme/frontier labels overstated the reasoning involved. The replacement,
`ms-cs-transaction-replay`, distinguishes rejected, rolled-back, committed, and
acknowledgement-lost requests; later balance changes make a previously rejected
request succeed. The builder independently computes the durable state.

All Master items continue through the existing build-time computed-answer and
positive-control checks, with adversarial controls for abstention and stateful
tool use. The builder remains the source of truth. Master prose regexes remain
coverage checks, not a semantic judge; they can miss equivalent wording or be
gamed by keyword stuffing. That limitation should temper score interpretation.

Webdev's removed `typeof null` question is a single memorized fact already
covered by richer coercion items. The other 45 snippets were executed in Node.
The retained suite measures JavaScript semantics, not browser rendering or
end-to-end web application development.

## Providers, UI and persistence

The focused UI pass adds search to the library, responsive action wrapping,
clearer headings, keyboard focus rings, and sticky modal actions. Provider
presets supply API roots, key variable names, and official docs while leaving
model IDs editable. Selecting another preset clears the unsaved key to avoid
carrying it across providers. Invalid/non-object header JSON is blocked.
Validation also runs through the form submission handler, so bypassing the Save
button cannot silently replace malformed headers or body parameters with `{}`.

API URL assembly now preserves explicit versioned roots such as Z.ai `/v4` and
Gemini `/v1beta/openai`. Presets include OpenAI, Alibaba/Qwen, DeepSeek, Z.ai, xAI,
Anthropic, Gemini, Groq, Mistral, OpenRouter and Ollama. Official references are
linked per preset in `frontend/src/lib/providers.ts`; no hosted account was
contacted for a completion. Alibaba's current documentation uses workspace-specific
regional roots: [Model Studio compatibility](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope).

The follow-up confirmation checked the five explicitly requested provider roots
against official documentation: [OpenAI](https://developers.openai.com/api/docs/guides/migrate-to-responses),
[Alibaba](https://www.alibabacloud.com/help/en/model-studio/base-url),
[DeepSeek](https://api-docs.deepseek.com/quick_start/agent_integrations/workbuddy/),
[Z.ai](https://docs.z.ai/guides/overview/quick-start), and
[xAI](https://docs.x.ai/developers/model-capabilities/text/generate-text).
Mocked request tests verify model discovery, completion paths, and environment-key
authentication for each; they do not establish live account/model availability.

Optional token pricing from the earlier workspace changes is also retained and
verified. Rates persist through duplication and are snapshotted for each run;
later profile edits do not change recorded costs. Negative/non-finite rates are
rejected. Missing priced token counts produce an unknown cost instead of an
understated total. Results and JSON/CSV/HTML exports include target cost estimates
based on manual rates; these do not include judge requests, retries, or provider
discounts such as caching.

Suite version bumps trigger existing in-place upgrades on startup. Old runs
retain prompt/benchmark snapshots. Migration `0004_retire_example` removes only
the original named example with its example provenance flag; startup no longer
seeds it. User-created suites and historical runs are retained.

## Reproduce validation

Confirmation results on September 27, 2026:

- Full backend run: **654 passed**, followed by **15 new provider/pricing checks
  passed** (669 distinct tests total); no skipped tests in the full run.
- Frontend: **29 passed**, with the TypeScript/production build passing.
- Python and Master suite builders match their committed JSON; HumanEval parity
  and all 164 reference completions passed in the backend run.
- Fresh application startup applies all four migrations, exposes exactly seven
  suites with **356 enabled prompts**, serves the built frontend, and returns a
  healthy API response.
- Ruff passes for the revised graders, URL helper, engine, endpoint schemas,
  new migrations/tests, and Python task builders; `git diff --check` is clean.

Backend API tests were run outside the restricted agent sandbox after confirming
that its AnyIO thread wakeups stalled before application startup. Tests used
temporary databases and mocked hosted providers. The session transcript is kept
local and ignored by Git.

```bash
cd backend
.venv/bin/python -m pytest -q
cd ..
python3 scripts/build_python_suite.py --check
python3 scripts/build_master_suite.py --check
cd frontend
npm run build
npm test
```

HumanEval remains upstream-compatible and its existing reference-solution and
source-parity tests remain part of the full backend test run.

The [qwen27b diagnostic pilot](CALIBRATION_QWEN27B_2026_09_29.md) documents measured formatting failures, repetition loops and prompt variants behind the Python 6.0.0 and Master 3.0.0 follow-up. It is a targeted pilot, not full cross-model calibration.

## Historical Master reduction to 50 questions

Version 4.0.0 removes five items without replacements: class-creation hook ordering
(`ms-py-class-creation-order`), minimal DFA counting (`ms-cs-minimal-dfa`), weak-acid
mixture pH (`ms-sci-coupled-diprotic-mixture`), entropy across a cycle
(`ms-sci-cycle-entropy`), and nested relativistic velocity composition
(`ms-sci-nested-velocity-legs`). The first two produced unfinished observations
lasting at least 271/300 seconds. The acid and entropy items passed but took
188.5/131.2 seconds in the pilot. The velocity item took about 257 seconds in the
older saved Master run; it was not rerun in the pilot. These are targeted duration
choices rather than a statistically established ranking across all questions or
models. The remaining 50 questions retain their keys and weights. The bundled
total at that revision was 351 prompts; historical runs retain their original suite snapshots.

The 50-question revision passed 25 Master, suite-loading and count tests, plus
Ruff and whitespace checks. A direct comparison confirmed that retained prompts,
grader configurations and weights match version 3.0.0.

## Master 5.0.0 and Cyber 1.0.0

The [Qwen Flash duration investigation](CALIBRATION_QWENFLASH_MASTER_2026_09_29.md)
records a full 50-request baseline and two completed concise-prompt trials.
Five lengthy manual workloads were retired, leaving 45 Master questions. The
remaining graders and weights are unchanged; numeric prompts disclose their
existing tolerances and ask for a single final answer. The user stopped endpoint
testing to conserve tokens, so the revised full-suite duration remains unmeasured.
The 15–30 minute goal is not a verified guarantee.

[Cyber](CYBER_SUITE.md) adds 18 original defensive-security questions with raw
JSON answers. Independent correct-response and error controls cover every item,
including authorization versus SQL binding, redirects, browser sinks, JWT and
CIDR boundaries, explicit denial, filesystem permissions, cryptography, distinct
users in alert windows, process ancestry, patch policy and HTTP framing. It uses
no tool calls, code execution or judge, and inherits global generation limits.
No live model calibration was performed for Cyber. At that revision, eight bundled
suites contained 364 questions (200 custom and 164 upstream HumanEval).

Local validation passed 49 Master/Cyber/seed tests and 449 suite-quality/revision
tests (498 total), plus builder parity, Ruff and whitespace checks. The Cyber
seeding test confirms automatic discovery and idempotence; the existing loader
upgrades Master by its new version while preserving historical run snapshots.

## Mini Master 1.0.0

[Mini Master](MINI_MASTER_SUITE.md) adds 25 deterministic prompts derived from
Master 5.0.0: ten selected code-output questions, three stateful tool questions,
and twelve compact variants. The class-scope/comprehension question is explicitly
excluded. The variants reduce enumeration and state-trace sizes, omit iterative
physical transitions and exponent calculation, use short evidence sets, and give
false-premise tasks closed JSON answers. Source IDs remain in the prompt tags.
Retained code keys are re-executed in CPython/Node; quantitative keys are computed
and counting/probability keys have independent checks. The builder grades a
correct response and non-answer controls for every item, plus Master's negative
tool controls. Separate tests pin reference answers, incorrect policy decisions,
output formats, exclusion, provenance, loading and native tool histories.

No endpoint calls were made for this addition. Weights and duration remain
unmeasured. Mini and full Master scores measure different question mixes and
should be compared within their respective suites. The full Master remains at
45 questions. Nine bundled suites now contain 389 prompts.

Validation passed 61 Mini Master/seed/native-tool tests and 475 suite-quality/
revision tests (536 total), plus fresh-build parity, Ruff and whitespace checks.
