# Cyber 2.0.0

Ten original hard defensive-security questions replace the former eighteen basic
scenarios. Each requires multiple decisions over explicit evidence and returns
closed-schema JSON. No judge, live lookup or tool execution is required.
Difficulty and weights are unmeasured design estimates.

| Stable ID | Reasoning required |
|---|---|
| `cy2-iam-intersection` | Identity, boundary and session intersections; independently classify explicit denies |
| `cy2-k8s-selector` | Namespace/pod AND, policy union and separate egress permission |
| `cy2-jwt-binding` | Verified signature versus permitted algorithm, issuer-bound key, token type, audience and time |
| `cy2-ssrf-pinning` | Per-hop scheme/host checks, mapped IPv6, full DNS sets and connected peer pinning |
| `cy2-gcm-reservation` | Every colliding batch pair and crash-safe counter reservation |
| `cy2-alert-event-time` | First-arrival deduplication and distinct failed users at event-time boundaries |
| `cy2-pid-reuse` | Historical process instances, exited intermediates, living descendants and reused PIDs |
| `cy2-http-framing` | Duplicate integer lengths, final transfer coding and reject/close decisions |
| `cy2-cache-tenant` | Cache hit trace, tenant leakage and effective isolation repairs |
| `cy2-oidc-subject` | Branch/environment claim forms, exact audience and excess wildcard trust |

The builder computes answer keys from the stated rules. Independent reviewed
keys and plausible mistakes appear in `backend/tests/test_cyber_suite.py`.
Primary references, adaptation rationale and limitations are in
[the refresh review](BENCHMARK_REFRESH.md).

Return one raw JSON object with exactly the requested keys. Object-key order
and whitespace are irrelevant; array order, labels and JSON types must match.
Duplicate/extra keys, fences, prose and malformed JSON score zero. For a valid
object each expected field contributes equal credit; full marks require all
fields. Empty responses earn zero. Global generation limits apply without
per-prompt token caps.

Rebuild with `python3 scripts/build_cyber_suite.py`; verify with `--check`.
Versioned seeding upgrades the existing Cyber definition in place, preserving
historical run snapshots. This evaluates supplied-evidence reasoning, not
practical incident handling or attack success.
