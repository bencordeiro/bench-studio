# Mini Master 3.0.0

Mini Master is a standalone 25-question sampler selected from the current seven
other suites. It has its own score and is excluded from the default six-suite
Index. Its selection favors composed rules and difficult edge cases; selection
difficulty and runtime have not been measured against models.

| Source suite | Questions | Selected topics |
|---|---:|---|
| Cyber | 4 | IAM policy intersections, JWT key binding, crash-safe nonce reservations, PID reuse |
| Terminal | 4 | ACL masks, boundary-safe regexes, bounded async cleanup, calendar-based log summaries |
| Python | 4 | Generator delegation, reflected operators, rolling totals, nested flattening |
| Web Dev | 4 | Thenable jobs, proxy receivers, response cloning, reentrant state updates |
| Agentic | 4 | Paginated revision joins, optimistic locking, partial outcomes, artifact dependencies |
| Instruction Following | 3 | Lipogram constraints, exact bullets/keywords, conditional stable redaction |
| HumanEval | 2 | `HumanEval/132` nested bracket subsequences and `HumanEval/147` modular triple counting |

All prompt messages, generation overrides, grading modes and grader contracts
are copied unchanged from source suites. Stable IDs are prefixed `mm3-`; tags
record the source file, source stable ID and source version. Item weights are
equal at 3.0 so the score averages these 25 questions. Source weights are not
reused to distort the sampler mix.

The former arrangements, GCD sum, compressor, Raft claim, successive tool-error
recovery and scoped-configuration questions are removed, along with the other
former Master-derived content. The original Master bundle and builder are
retired. Migration removes the original definition while keeping historical
run snapshots and responses.

The sampler uses deterministic and execution grading. Terminal implementations
require Python 3.11+; HumanEval retains its original body-completion contract.
It inherits global generation settings without per-question token caps.
No judge or external network is needed.

`scripts/build_mini_master_suite.py` records the exact selection and rebuilds
the bundle. Run it after updating any source suite; `--check` detects drift.
Regression checks prove each selected question matches its source and version,
all seven sources are represented, the count is 25, old questions are absent,
and version upgrades preserve historical run snapshots. Source-suite tests
verify the underlying answer keys and functional references.

See [research, validation and licensing](BENCHMARK_REFRESH.md) for the selected
Terminal-Bench adaptations and HumanEval's existing attribution under
`data/humaneval/`.
