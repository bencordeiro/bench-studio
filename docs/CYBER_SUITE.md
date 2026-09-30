# Cyber 1.0.0

Cyber contains 18 original defensive-security scenarios. Each gives a fixed
setup, explicit policy assumptions, and a short JSON output contract. The mix
includes vulnerability identification and repairs, authorization decisions,
hardening, cryptography, detection, incident scope, and patch triage. No live
lookup, tool use, code execution or judge is required to answer or grade them.
Difficulty and weights are design estimates; no endpoint tokens were used to
test this suite. It does not measure practical incident handling or attack success.

`scripts/build_cyber_suite.py` generates the bundle. Policy and log keys are
computed locally; vulnerability classifications are reviewed reference labels.
The independent controls in `backend/tests/test_cyber_suite.py` check every
answer plus tempting mistakes involving boundaries, policy priority and types.
Run `python3 scripts/build_cyber_suite.py --check` to detect bundle drift.

## Answer-key review

| Stable ID | Correct result | Decisive assumption |
|---|---|---|
| `cy-tenant-object` | A and B vulnerable; IDOR | Only the authenticated session tenant establishes ownership; SQL binding does not enforce authorization |
| `cy-sql-identifier` | A and C vulnerable; allowlist column map | Raw or uppercased input remains SQL syntax; map only to constant identifiers |
| `cy-ssrf-redirect` | SSRF; validate every hop | The redirect bypasses the initial host, scheme and address policy |
| `cy-csrf-get` | CSRF; POST with validated token | The stated Lax behavior sends cookies on the mutating top-level GET; the fix removes GET mutation |
| `cy-dom-text-sink` | A and C unsafe; textContent | The name is literal text; quote encoding alone does not neutralize HTML markup |
| `cy-path-boundary` | P1 and P3; commonpath equals root | Canonical POSIX path components differ from shared string prefixes; symlinks and races excluded |
| `cy-jwt-claims` | T1 and T6 accepted | Signature, issuer, audience and `nbf <= now < exp` all required, with no skew |
| `cy-tls-hostname` | Reject; hostname match missing | The trusted certificate SAN authenticates a different DNS host |
| `cy-egress-cidr` | F1 and F4 allowed | First-match rules; the /20 ends before 10.42.32.0; the earlier private-address deny wins |
| `cy-iam-deny` | R1 and R5 allowed; explicit deny for R2 | Explicit deny overrides the specific allow; no other grants exist |
| `cy-linux-directory` | Can replace; remove group directory write | Directory write/search permits replacement despite the file's read-only permission for alex |
| `cy-container-volume` | P2 writable | The writable mount is distinct from the read-only root filesystem |
| `cy-gcm-nonce` | Nonce reuse; confidentiality and integrity affected | Different messages reuse nonces under the same persistent key; durable reservation or key rotation prevents it |
| `cy-password-storage` | B; fast offline guessing | The specified policy requires a memory-hard KDF; salts alone do not slow individual guesses |
| `cy-alert-window` | Only 203.0.113.61 | Open left boundary, closed right boundary, distinct failed usernames only |
| `cy-process-lineage` | 100, 110, 120, 130 | Complete snapshot; all descendants, no ancestors or unrelated tree |
| `cy-patch-priority` | V3, V1, V4, V2 | Apply the stated two-group policy, then descending CVSS within each group |
| `cy-http-framing` | Request smuggling; reject and close | Proxy and backend disagree on persistent-connection message boundaries |

## Grading contract

The final response must be one raw JSON object with exactly the requested keys.
Object-key order and whitespace are irrelevant. Labels, array order, contents
and JSON types must match: `false` is not integer `0`, and PID integers are not
strings. Extra fields, duplicate keys, Markdown fences, prose and malformed JSON
score zero. Empty replies and empty objects also score zero. For valid objects,
each correctly answered requested field earns equal partial credit; a missing or
incorrect field loses its credit, and full marks require every field to match.
There are no points simply for including a field. All prompts inherit the saved
global token and inactivity limits; no per-question token caps are bundled.

## Primary references

These references support the security principles; scenarios and policies are
original and self-contained rather than excerpts of a public benchmark.

- Object authorization: [MITRE CWE-639](https://cwe.mitre.org/data/definitions/639.html). SQL construction: [MITRE CWE-89](https://cwe.mitre.org/data/definitions/89.html).
- Browser and request controls: OWASP prevention guidance for [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) and [XSS](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html).
- Token claims: [RFC 7519](https://www.rfc-editor.org/rfc/rfc7519.html). Identity policy denial: [AWS IAM evaluation logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic_policy-eval-denyallow.html).
- File replacement: [Linux unlink semantics](https://man7.org/linux/man-pages/man2/unlink.2.html). Container mounts: [Kubernetes security contexts](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/) and [volumes](https://kubernetes.io/docs/concepts/storage/volumes/).
- GCM nonce reuse: [RFC 5116, section 5.1.1](https://www.rfc-editor.org/rfc/rfc5116.html#section-5.1.1). Password KDFs: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
- HTTP message boundaries: [RFC 9112, section 6.3](https://www.rfc-editor.org/rfc/rfc9112.html#section-6.3).
