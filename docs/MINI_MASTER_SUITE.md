# Mini Master 2.0.0

Mini Master is a 23-question cross-domain suite adapted from Master 5.0.0.
Ten selected items preserve Master's code and tool-use challenges; twelve compact
variants reduce repeated calculation, state tracing and evidence volume, and one
original Python question tests mutation and alias rebinding in nine lines.
**Class scope versus comprehension scope is excluded**, as are Master's retired
duration workloads. Version 2.0.0 also removes singledispatch ambiguity, except*
splitting/re-raising, and structuredClone after the user reported that these
questions hit the global 16k-token limit. No live retest was made.
Full Master remains unchanged at 45 questions.

Every question has a deterministic grader and inherits global token/inactivity
limits. Code snippets are executed locally while building their keys; the model's
response is graded as output text, not executed. Tool questions use the existing
Hermes/native adapter and supplied tool histories; no real tools are executed.
The suite requires no judge. Validation made no model or endpoint calls. Difficulty,
weights and runtime are unmeasured; fewer questions and steps do not guarantee a
specific duration on a reasoning model.

## Selection

| Domain | Questions | Selection or condensed variant |
|---|---:|---|
| Python output reasoning | 4 | Reflected operator priority, ExitStack, groupby/tee, and the new mutation-before-error/alias-rebinding question |
| JavaScript output reasoning | 4 | Primitive conversion, generator return/finally, field initialization, proxy receivers |
| Math | 3 | Six-letter multiset; three-flip posterior and a different coin; bounded ordered GCD sum |
| Systems | 3 | Short two-segment SLRU trace; ten-event three-process clock; six durable transfer requests |
| Physics and engineering | 2 | Already-rolling cylinder over two regimes; compressor/cooler with ideal temperature supplied |
| False premises | 2 | Standard Raft fault model; non-unique product from a sum, both with closed JSON answers |
| Stateful tool use | 3 | Customer-field propagation, cumulative retry correction, withholding an unfunded transfer |
| Context synthesis | 2 | Five scoped configuration releases with an untrusted note; eight-row replay/reversal ledger |

Seven code snippets and their graders are retained from Master. Three tool
scenarios retain their schemas, history and grading with a brief-answer reminder.
The twelve other prompts are compact variants, not claims of equal difficulty
to their full-Master counterparts. The 22 Master-derived prompts have a
`source-ms-...` provenance tag; the replacement has an `original` tag. Every
prompt has a distinct `mm-...` stable ID. Because content overlaps, the two suites'
scores are not independent measurements. Compare models on the same suite/version.

## Reference keys for the compact variants

| Mini stable ID | Key | Control |
|---|---|---|
| `mm-py-mutation-before-error` (original) | True False 3 6 | Execution verifies that list mutation survives the failed tuple assignment and ordinary addition creates a new list |
| `mm-math-multiset` | 84 | Memoized recurrence agrees with exhaustive distinct-permutation enumeration |
| `mm-math-second-coin` | 0.4625 | Exact-rational posterior mixture agrees with joint/evidence calculation |
| `mm-math-gcd-triples` | 624 | Direct triple enumeration agrees with a totient/divisibility sum |
| `mm-cs-slru` | 11 hits; probation E,C; protected B,A | Policy simulation, segments in LRU-to-MRU order |
| `mm-cs-vector-clock` | [4,2,4] | Merge before increment, stamped sends, receive increment included |
| `mm-cs-transaction` | A=75, B=15, C=5; k1,k2,k3 committed | Durable deduplication, rollback and insufficient-funds retry; total balance conserved |
| `mm-sci-rolling` | 141.875 m | Translational plus rotational energy, then constant deceleration |
| `mm-auto-intercooler` | 58.85 °C | Efficiency applied to rise; effectiveness applied above ambient; Kelvin conversion last |
| `mm-abs-raft` | unsupported; CRASH | Rejects the claim about unmodified standard Raft providing Byzantine tolerance |
| `mm-abs-underdetermined` | unsupported; products [21,24] | Two admissible witnesses have different products |
| `mm-context-config` | region=ap, workers=8, audit=true | Only approved prod releases apply; notes never override configuration |
| `mm-context-ledger` | 155; e1,e2,e5,e6,e7 applied | Filter scope/status, deduplicate events, apply reversal as a separate signed entry |

Numeric prompts state their tolerances. Integer counts require exact answers;
the coin probability accepts absolute error 0.0005 and the physical temperatures/
distances accept absolute error 0.05 in the requested units. JSON prompts reject
extra fields, fences and prose. Key order and whitespace are irrelevant; array
order, values and types must match. JSON partial credit is per correctly answered
field, with no credit merely for field presence. The transfer refusal uses Master's
existing short-prose grader and a gate that awards zero if the prohibited action
is called, even if an accompanying explanation recognizes insufficient funds.

## Rebuild and local verification

```bash
backend/.venv/bin/python scripts/build_mini_master_suite.py --check
cd backend
.venv/bin/pytest tests/test_mini_master_suite.py tests/test_native_tools.py tests/test_seed_suites.py -q
```

The builder reads the committed Master bundle, re-executes the seven selected code
snippets and the original replacement, recomputes compact variants, and checks correct/incorrect responses
through the app's real graders. It verifies byte-identical output with `--check`.
Changing inherited Master content requires regenerating and reviewing Mini Master
and bumping its version if its shipped questions or grading change. Startup discovers
the new bundle automatically; older saved run snapshots remain intact.
