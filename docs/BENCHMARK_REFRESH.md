# Benchmark refresh — October 29, 2026

This revision refreshes the five requested suites, replaces Mini Master, retires
Master, and separates the six-suite Index from the standalone sampler. Existing
run snapshots and answers remain historical evidence; new scores should be
compared using the same suite version. No model endpoint calls were used.

## Checklist

- [x] Research official tasks and primary specifications; reproduce the sed key.
- [x] Refresh Terminal, Python, Cyber, Web Dev and Agentic questions.
- [x] Remove Master; select 25 current questions for Mini Master.
- [x] Default Index to the six core suites; exclude Mini Master and HumanEval.
- [x] Fix library error feedback, direct run navigation and run-selection UX.
- [x] Finish answer-key, functional grader, migration and UI checks.

| Suite | Version | Questions | Change |
|---|---|---:|---|
| Terminal | 3.0.0 | 15 | Keep 12 existing tasks; add three official-task adaptations |
| Python | 8.0.0 | 40 | Replace zip; remove the other five named questions |
| Cyber | 2.0.0 | 10 | Replace the basic scenarios with ten original multi-step problems |
| Web Dev | 6.0.0 | 45 | Replace ten elementary coercion/arithmetic questions |
| Agentic | 5.0.0 | 15 | Replace the six named questions with stateful decisions |
| Mini Master | 3.0.0 | 25 | Selected current questions from seven source suites |

## Official benchmark research and adaptation limits

The [official catalog](https://www.tbench.ai/benchmarks) lists Terminal-Bench
4.0 as the latest published release checked on this date; no official v5 was
listed. Its [release](https://github.com/harbor-framework/terminal-bench/releases/tag/v4.0.0)
also documents removals and resource changes. Official tasks use container
environments and artifact verifiers. Bench Studio evaluates model responses,
so copying a filesystem instruction alone would produce an unanswerable item.

We reviewed the instructions, verifiers and solutions of three suitable public
Terminal-Bench 2.0 tasks, plus Git recovery, WAL recovery and multibranch
deployment tasks. The selected three preserve a useful implementation contract
without requiring a new live terminal-agent harness:

| Upstream task | Studio artifact | Deliberate changes |
|---|---|---|
| [regex-log](https://github.com/harbor-framework/terminal-bench-2/blob/main/regex-log/instruction.md) | `log_date_pattern()` returns a regex | Replaces regex.txt; original calendar/IP fixtures; explicit LF and ASCII boundaries; no upstream oracle copied |
| [cancel-async-tasks](https://github.com/harbor-framework/terminal-bench-2/blob/main/cancel-async-tasks/instruction.md) | `async run_tasks(...)` | Direct cancellation replaces keyboard interrupt; specifies queued invocation, awaited cleanup, exception behavior and no orphan tasks |
| [log-summary-date-ranges](https://github.com/harbor-framework/terminal-bench-2/blob/main/log-summary-date-ranges/instruction.md) | `summarize_logs(files,today)` returns 15 rows | In-memory files replace a directory and CSV artifact; new dates, sources, leap-year and window-boundary fixtures; severity-token behavior is explicit |

These are **adaptations**, not unmodified official questions or official
Terminal-Bench scores. Fixture data, Python reference solutions and tests are
new. The Apache 2.0 license and attribution are in
[third_party/terminal-bench](../third_party/terminal-bench/ATTRIBUTION.md).
The upstream canary is retained in the adaptation source. Upstream tasks are
linked for provenance; source repositories may change after this review.

The regex tests cover false IPs, leading zeros, calendar validity, alphanumeric
boundaries, multiple dates and cross-line leakage. Async tests use events and
cooperative scheduling, including cancellation with queued work and asynchronous
cleanup; they reject the common bare-gather sibling-cleanup bug. Log tests
independently accumulate expected rows across year, month, leap-day, open/future
and inclusive window boundaries. Reference solutions pass the actual execution
grader, not just a separate Python interpreter.

## Original hard questions and their primary references

Cyber's ten tasks require concrete decisions over supplied evidence. They do
not award points for naming a vulnerability from a short menu. All answer keys
are computed, with separate reviewed keys and plausible-error controls.

| Topic | Source grounding and reasoning tested |
|---|---|
| Identity/boundary/session policy intersection | [AWS IAM evaluation](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html): intersect grants and apply explicit denies; resource-policy exceptions excluded |
| Kubernetes network peers | [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/): AND within a peer, additive policies, and both ingress/egress |
| JWT substitution | [RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html): algorithm permissions, issuer/key binding and access-token type, plus audience/time |
| SSRF destination checks | [OWASP SSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html): redirects, mixed DNS sets and pinning; exercise defines its own permitted address ranges |
| GCM crash consistency | [RFC 5116](https://www.rfc-editor.org/rfc/rfc5116.html#section-5.1.1): uniqueness per key; overlap across batches and durable preallocation |
| Alert windows | Original closed-policy SIEM fixture: first-arrival deduplication, event time, distinct users and open-left windows |
| Process containment | Original complete lifetime/ancestry fixture: process instances survive PID reuse and exited intermediates |
| HTTP request framing | [RFC 9112 §6.3](https://www.rfc-editor.org/rfc/rfc9112.html#section-6.3): duplicate integer lengths and transfer coding; gateway's reject-both rule is explicitly stricter than the general standard |
| Tenant cache isolation | [RFC 9111](https://www.rfc-editor.org/rfc/rfc9111.html): representation selection composed with a supplied tenant-authorization trace |
| OIDC deployment trust | [GitHub's AWS OIDC guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws): branch/environment subjects and exact audience; legacy subject format pinned explicitly |

Web replaces `map(parseInt)`, default sort, unary coercion, float addition,
array/object addition, basic equality, bitwise coercion, negative zero, empty
Math extrema and parseInt/Number edge cases. New programs exercise:

- URLSearchParams liveness and normalization, grounded in the
  [WHATWG URL standard](https://url.spec.whatwg.org/#urlsearchparams).
- Response cloning and consumed bodies, grounded in the
  [Fetch standard](https://fetch.spec.whatwg.org/#dom-body-clone).
- Synchronous abort dispatch, thenable jobs, serialization hooks, inherited
  proxy receivers, transferred buffers, async-finally cleanup and reentrant
  subscriber snapshots. The [ECMAScript specification](https://tc39.es/ecma262/)
  and [MDN's Proxy reference](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Proxy)
  support the language behavior; actual Node.js execution produces the keys.
- HTTP current age and shared freshness with Vary, grounded in
  [RFC 9111 §4.2.3](https://www.rfc-editor.org/rfc/rfc9111.html#section-4.2.3).

Python replaces zip consumption with generator delegation, injected exceptions,
returned values and cleanup. The [Python yield-expression reference](https://docs.python.org/3/reference/expressions.html#yield-expressions)
supports the rules; CPython produces the exact output. Mutable defaults, implicit
exception chaining, basic grouping, latest records and missing ranges are removed
from the active suite. Retired function definitions remain in the task archive;
the builder excludes them.

Agentic's six new original scenarios use paginated revision reconciliation,
optimistic locking, mixed committed/unknown/rejected outcomes, capped refunds,
immutable ownership despite injected notes, and workflow artifact versions.
[BFCL's multi-step evaluation](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)
and [tau-bench](https://github.com/sierra-research/tau-bench) informed the move
toward policy and state dependencies. No benchmark questions were copied from
either. Our tasks ask for the next safe action in a **fixed supplied history**;
they do not measure live multi-turn task completion. Dependent history calls
appear after their prerequisite results, and native API histories are validated.

## Correctness audit

The GNU sed answer is **13**, with selected lines 6–11, 13–16 and 19–21.
The second regexp begins testing on the next input line; a closing-tag string
still matches because sed does not parse JavaScript. A one-line opening/closing
block can therefore extend its range through later input. Actual GNU sed
execution checks both line count and selected line numbers. Existing Git and
SQLite keys are also reproduced independently; none of these three keys changed.

Every retained Python and web snippet is re-executed in tests. New Cyber keys
are independently checked. Every new Agentic item has compliant and violating
controls; tool calls cannot earn full credit with invented IDs, stale versions,
wrong types or extra actions. New functional contracts are tested through the
production grader. No additional wrong retained answer key was found during
this review; this is not a proof that every possible answer or interpretation
has been enumerated.

## Versioning and UX

All changed suites have version increments, so bundled seeding upgrades existing
definitions in place. Original run snapshots are preserved. Master's builder,
bundle and dedicated tests are removed. Migration 0005 removes definitions with
the original Master name and provenance tags, cleans prompt/message children,
and removes those retired IDs from explicit Index selections. Similarly named
custom suites and all saved runs remain.

The default Index averages quality equally across Python, Instruction Following,
Cyber, Terminal, Agentic and Web Dev. Mini Master and HumanEval remain separately
runnable. Explicit user Index customizations remain supported.

The library now links directly to a preselected run, distinguishes loading errors
from empty data, and reports failed create/duplicate/delete/import operations.
The run form has separate shortcuts for the six core suites and Mini Master,
clear selection, and a retryable library-loading error. Labels explain the
sampler's independence; settings restore the six current defaults.

## Rebuild and verify

Final validation: **786 backend tests passed** across four isolated groups;
**55 frontend tests passed**. TypeScript typecheck, the production frontend
build, lint for all changed Python files, all four bundle-builder checks and
`git diff --check` passed. Backend API checks ran outside the restricted sandbox
after an unrelated minimal FastAPI TestClient also hung inside it; the same
minimal reproduction succeeded outside. No production database or model
endpoint was used in validation.

```bash
backend/.venv/bin/python scripts/build_cyber_suite.py --check
backend/.venv/bin/python scripts/build_python_suite.py --check
backend/.venv/bin/python scripts/build_refreshed_suites.py --check
backend/.venv/bin/python scripts/build_mini_master_suite.py --check
cd backend && .venv/bin/pytest
cd ../frontend && npm run typecheck && npm test && npm run build
```

New difficulty/weight assignments are design estimates. No model calibration,
new pass-rate claim, or duration guarantee is made. Terminal implementations
require Python 3.11+; the new web snippets use Node.js 22+ web APIs. Those runtimes
are needed for local verification, not as external tools for output prediction.
