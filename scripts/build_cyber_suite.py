"""Build ten original multi-step defensive security questions. No model calls.

Security rules are grounded in primary references in docs/BENCHMARK_REFRESH.md.
All keys are computed from explicit rules, then checked against independent keys.
"""
from __future__ import annotations

import argparse
import fnmatch
import ipaddress
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "backend/app/seed/suites/cyber.json"


def build():
    prompts = []

    def add(sid, title, category, body, answer, evidence):
        prompts.append({
            "stable_id": sid, "title": title, "description": evidence,
            "category": "cyber/" + category, "difficulty": "hard",
            "tags": ["cyber", "defense", "original", "unmeasured", "computed-answer"],
            "importance_weight": 3.0, "position": len(prompts), "enabled": True,
            "grading_mode": "deterministic", "generation_overrides": {"temperature": 0.0},
            "grader_config": {"type": "json", "require_valid_json": True, "allow_code_fences": False,
                              "allow_extra_fields": False, "expected_field_values": answer, "points": 100.0},
            "messages": [{"role": "user", "position": 0, "content": body.strip()
                          + "\n\nReturn one raw JSON object with exactly these keys: "
                          + ", ".join(answer) + ". Follow all stated array orders. No explanation or Markdown."}],
        })

    requests = [
        ("R1", "GetObject", "reports/public/a", True),
        ("R2", "GetObject", "reports/private/a", True),
        ("R3", "PutObject", "reports/public/a", True),
        ("R4", "GetObject", "reports/public/quarantine/a", True),
        ("R5", "GetObject", "reports/public/a", False),
        ("R6", "DeleteObject", "reports/public/a", True),
        ("R7", "GetObject", "reports/publicity/a", True),
    ]
    decisions = []
    for rid, action, path, tls in requests:
        identity = action in {"GetObject", "PutObject"} and path.startswith("reports/")
        boundary = action == "GetObject" and path.startswith("reports/public/")
        session = action == "GetObject" and path.startswith("reports/")
        denied = path.startswith("reports/public/quarantine/") or not tls
        decisions.append((rid, identity and boundary and session and not denied))
    add("cy2-iam-intersection", "Intersect identity, boundary and session grants with explicit denies", "cloud-policy", '''
Evaluate same-account S3 requests by an assumed role. No resource policies,
ACLs, SCPs or RCPs grant access. The identity policy allows GetObject and
PutObject on reports/*. The permissions boundary allows only GetObject on
reports/public/*. The session policy allows GetObject on reports/*.
An identity statement explicitly denies GetObject on reports/public/quarantine/*.
A separate identity statement denies ALL actions when TLS is false.
Here * matches any suffix; slashes are literal. Resources shown are bucket/key
suffixes of object ARNs. Effective access requires an allow from ALL THREE
policy layers; ANY matching explicit deny wins. A boundary is not a grant.
Requests (ID, action, bucket/key, TLS):
R1 GetObject reports/public/a true
R2 GetObject reports/private/a true
R3 PutObject reports/public/a true
R4 GetObject reports/public/quarantine/a true
R5 GetObject reports/public/a false
R6 DeleteObject reports/public/a true
R7 GetObject reports/publicity/a true
Return allowed and explicit_deny as ascending request-ID arrays. A request
may lack an allow as well as have an explicit deny; explicit_deny lists every
request matching a deny, independently of other layers.
''', {"allowed": [rid for rid, ok in decisions if ok],
      "explicit_deny": [rid for rid, _, path, tls in requests if not tls or path.startswith("reports/public/quarantine/")]},
        "AWS policy intersection and explicit denial; excludes resource-policy bypass cases.")

    flows = [
        ("F1", "ops", "audit", 8443, True), ("F2", "ops", "web", 8443, True),
        ("F3", "dev", "audit", 8443, True), ("F4", "ops", "audit", 443, True),
        ("F5", "dev", "web", 443, True), ("F6", "ops", "audit", 8443, False),
        ("F7", "prod", "web", 443, True),
    ]
    ingress_only = [fid for fid, ns, app, port, _ in flows
                    if (ns == "ops" and app == "audit" and port == 8443) or (ns == "prod" and port == 443)]
    allowed = [fid for fid, ns, app, port, egress in flows
               if egress and ((ns == "ops" and app == "audit" and port == 8443) or (ns == "prod" and port == 443))]
    add("cy2-k8s-selector", "NetworkPolicy peer AND, rule OR and two-sided isolation", "network-policy", '''
All flows target a prod/api pod isolated for ingress. Its policies are additive.
P1 allows TCP 8443 from ONE peer entry containing BOTH namespaceSelector team=ops
and podSelector app=audit. Both selectors must match the source.
P2 allows TCP 443 from namespaces with team=prod (any source pod label).
All namespaces' team labels are their names below. No other ingress allows.
Each source is also isolated for egress: the final column is the independently
computed result of its egress policies for this destination and port.
F1 ops  audit 8443 true
F2 ops  web   8443 true
F3 dev  audit 8443 true
F4 ops  audit 443  true
F5 dev  web   443  true
F6 ops  audit 8443 false
F7 prod web   443  true
Fields: ID, source namespace, source app label, TCP port, source egress allowed.
There is no NAT, host networking, named port or CNI ambiguity. A connection
requires BOTH permitted egress and permitted ingress. Return ingress_matches
(ignoring egress) and allowed (end-to-end) as ascending flow-ID arrays.
''', {"ingress_matches": ingress_only, "allowed": allowed},
        "Kubernetes policy union does not turn selectors within a single peer into OR.")

    tokens = [
        ("T1", "corp", "K1", "RS256", "at+jwt", ["ledger"], 90, 101, True),
        ("T2", "corp", "K1", "HS256", "at+jwt", ["ledger"], 90, 101, True),
        ("T3", "partner", "K1", "RS256", "at+jwt", ["ledger"], 90, 101, True),
        ("T4", "corp", "K1", "RS256", "id+jwt", ["ledger"], 90, 101, True),
        ("T5", "partner", "K2", "RS256", "at+jwt", ["web", "ledger"], 100, 101, True),
        ("T6", "corp", "K1", "RS256", "at+jwt", ["ledger"], 90, 100, True),
        ("T7", "corp", "K1", "RS256", "at+jwt", ["web"], 90, 101, True),
        ("T8", "partner", "K2", "RS256", "at+jwt", ["ledger"], 101, 110, True),
        ("T9", "partner", "K2", "RS256", "at+jwt", ["ledger"], 90, 110, False),
    ]
    def valid(t, complete=True):
        _, iss, key, alg, typ, aud, nbf, exp, sig = t
        base = sig and iss in {"corp", "partner"} and "ledger" in aud and nbf <= 100 < exp
        return base and (not complete or (key == {"corp": "K1", "partner": "K2"}[iss]
                                         and alg == "RS256" and typ == "at+jwt"))
    add("cy2-jwt-binding", "Cross-issuer key binding and cross-JWT substitution", "authentication", '''
At time 100 the ledger API accepts only RS256 access tokens (typ=at+jwt).
Configured issuer/key bindings: corp->K1, partner->K2; no others are trusted.
Require aud containing ledger and nbf <= 100 < exp, with zero clock skew.
The sig column is an independently verified cryptographic result for the
specified algorithm and key bytes; it does NOT establish algorithm permission
or which issuer is entitled to that key. All fields below are verified contents.
A buggy validator checks only sig, issuer membership, audience and time.
Return accepted under the COMPLETE policy and buggy_only: IDs the buggy
validator accepts that the complete policy rejects, both ascending.
Fields: ID, issuer, key, algorithm, typ, audience, nbf, exp, sig.
''' + "\n" + json.dumps(tokens),
        {"accepted": [t[0] for t in tokens if valid(t)],
         "buggy_only": [t[0] for t in tokens if valid(t, False) and not valid(t)]},
        "RFC 8725: algorithm selection, issuer-bound keys and mutually exclusive token profiles.")

    attempts = [
        ("A", [("https", "media.test", ["203.0.113.9"], "203.0.113.9"),
                ("https", "cdn.test", ["198.51.100.8"], "198.51.100.8")]),
        ("B", [("https", "media.test", ["203.0.113.9"], "203.0.113.9"),
                ("https", "cdn.test", ["198.51.100.8", "::ffff:127.0.0.1"], "198.51.100.8")]),
        ("C", [("https", "media.test", ["203.0.113.9"], "127.0.0.1")]),
        ("D", [("https", "media.test", ["203.0.113.9"], "203.0.113.9"),
                ("http", "cdn.test", ["198.51.100.8"], "198.51.100.8")]),
        ("E", [("https", "other.test", ["203.0.113.9"], "203.0.113.9")]),
        ("F", [("https", "cdn.test", ["::ffff:198.51.100.8"], "::ffff:198.51.100.8")]),
    ]
    def normalized(value):
        address = ipaddress.ip_address(value)
        return address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address
    safe_nets = [ipaddress.ip_network(n) for n in ("203.0.113.0/24", "198.51.100.0/24")]
    first_bad = {}
    for aid, hops in attempts:
        for i, (scheme, host, dns, peer) in enumerate(hops, 1):
            addresses = [normalized(a) for a in dns]
            if not (scheme == "https" and host in {"media.test", "cdn.test"} and addresses
                    and all(any(a in net for net in safe_nets) for a in addresses)
                    and normalized(peer) in addresses):
                first_bad[aid] = i
                break
    add("cy2-ssrf-pinning", "Redirect validation with mixed DNS answers and pinned peers", "request-security", '''
Evaluate each proposed fetch trace independently. At EVERY hop require HTTPS,
host media.test or cdn.test, a nonempty DNS result containing ONLY addresses in
203.0.113.0/24 or 198.51.100.0/24, and actual connected peer in that checked DNS
set. These documentation ranges stand for permitted external networks in this
closed exercise; do NOT use a library's is_global classification.
Normalize IPv4-mapped IPv6 to IPv4 BEFORE all address comparisons. Other IPv6
addresses are not allowed. Reject BEFORE sending HTTP if any condition fails.
Each trace lists hops as [scheme, host, checked DNS answers, actual peer].
Return accepted trace IDs ascending and rejected as ascending [ID, first_bad_hop]
pairs (hop numbers start at 1). A rejected trace stops at that hop.
''' + "\n" + json.dumps(attempts),
        {"accepted": [aid for aid, _ in attempts if aid not in first_bad],
         "rejected": [[aid, hop] for aid, hop in sorted(first_bad.items())]},
        "OWASP SSRF defenses compose redirect checks, full answer validation and connection pinning.")

    # Nonces are (key, worker-prefix, counter); counter intervals are half-open.
    batches = [("B1", "K1", "w1", 0, 4), ("B2", "K1", "w2", 0, 4),
               ("B3", "K1", "w1", 4, 7), ("B4", "K1", "w1", 2, 5),
               ("B5", "K2", "w1", 0, 4), ("B6", "K1", "w2", 3, 6)]
    overlaps = []
    for i, (bid, key, prefix, start, end) in enumerate(batches):
        for aid, oldkey, oldprefix, oldstart, oldend in batches[:i]:
            if key == oldkey and prefix == oldprefix and max(start, oldstart) < min(end, oldend):
                overlaps.append([aid, bid, min(end, oldend) - max(start, oldstart)])
    overlaps.sort()
    add("cy2-gcm-reservation", "GCM nonce collisions across worker prefixes and crash rollback", "cryptography", '''
A service uses AES-GCM. The nonce is a fixed-width concatenation of worker
prefix and counter, under the specified key. Different key IDs mean genuinely
different random keys. Prefixes are globally distinct byte strings; no encoding
ambiguity or overflow exists. Every counter below encrypts a DIFFERENT message.
Each batch is [ID, key ID, worker prefix, start counter inclusive, end exclusive].
Return collisions as [earlier_batch_ID, later_batch_ID, reused_nonce_count],
sorted lexicographically by the ID pair. Include every overlapping batch pair.
Also evaluate repairs under arbitrary process crashes:
A persists the next counter only AFTER ciphertext has been emitted.
B atomically reserves a disjoint counter range in durable shared storage BEFORE
  any encryption; after a crash it discards the unused remainder of that range.
C resets the counter to zero while retaining key and prefix after each restart.
D uses a genuinely fresh key before resetting its counter after each restart.
Return safe_repairs as alphabetical labels guaranteeing no reuse in this model.
''' + "\n" + json.dumps(batches),
        {"collisions": overlaps, "safe_repairs": [label for label, safe in [("A", False), ("B", True), ("C", False), ("D", True)] if safe]},
        "RFC 5116 nonce uniqueness is per key; persist reservation before encryption, not after emission.")

    events = [
        ("e1", 0, "ipA", "a", "FAIL"), ("e2", 1, "ipA", "b", "FAIL"),
        ("e3", 5, "ipA", "c", "FAIL"), ("e4", 10, "ipA", "d", "FAIL"),
        ("e5", 10, "ipA", "e", "FAIL"), ("e5", 11, "ipA", "f", "FAIL"),
        ("e6", 12, "ipA", "d", "FAIL"), ("e7", 13, "ipA", "g", "SUCCESS"),
        ("e8", 13, "ipB", "a", "FAIL"), ("e9", 9, "ipB", "b", "FAIL"),
        ("e10", 12, "ipB", "c", "FAIL"), ("e11", 14, "ipB", "d", "FAIL"),
        ("e12", 14, "ipA", "f", "FAIL"),
    ]
    seen, accepted_events = set(), []
    for event in events:
        if event[0] not in seen:
            seen.add(event[0])
            accepted_events.append(event)
    counts = []
    for end in (10, 14):
        for ip in ("ipA", "ipB"):
            users = {u for _, time, source, u, status in accepted_events
                     if source == ip and status == "FAIL" and end - 10 < time <= end}
            counts.append([end, ip, len(users)])
    add("cy2-alert-event-time", "Deduplicate out-of-order alerts at event-time window boundaries", "detection", '''
A finalized authentication batch appears in ARRIVAL order below. Deduplicate
globally by event ID: FIRST arrival wins, even if a later payload differs.
Then for each evaluation time T=10 and T=14 count DISTINCT failed usernames
per IP in (T-10,T]. Ignore SUCCESS records entirely; they do not reset failures.
This is a finalized batch, so late arrivals are included by EVENT time. Do not
use arrival position as a time or count the same username twice in a window.
Return counts as [T, IP, distinct_users], ordered by T then IP, including zeros.
Return alerts as [T, IP] for counts >=4 in the same order. Fields below:
[event ID, event time seconds, source IP label, username, status].
''' + "\n" + json.dumps(events),
        {"counts": counts, "alerts": [[end, ip] for end, ip, count in counts if count >= 4]},
        "Original event-time SIEM fixture; independent first-arrival dedup and distinct-user window checks.")

    processes = [
        ("P1", 100, 0, None, 20), ("P2", 110, 2, "P1", 8),
        ("P3", 120, 3, "P2", None), ("P4", 130, 4, "P3", None),
        ("P5", 110, 9, "Q1", None), ("P6", 140, 10, "P5", None),
        ("Q1", 10, -1, None, None), ("P7", 150, 6, "P1", 7),
        ("P8", 150, 11, "Q1", None), ("P9", 160, 6, "P7", None),
    ]
    parents = {key: parent for key, _, _, parent, _ in processes}
    def descends(key):
        while key is not None:
            if key == "P1":
                return True
            key = parents[key]
        return False
    targets = sorted((pid, key) for key, pid, start, _, end in processes
                     if start <= 12 and (end is None or 12 < end) and descends(key))
    add("cy2-pid-reuse", "Contain historical descendants without following reused PIDs", "incident-response", '''
At snapshot time 12, contain root process instance P1 and all its descendants.
The table is complete and parent_instance records the creating process instance
at birth; descendants remain in scope even if an intermediate parent exited
or the kernel later reparents them. PID reuse does NOT establish ancestry.
Intervals of life are [start,end); null end means still alive. Process keys are
unique instance IDs. Include only currently living in-scope processes, ordered
by numeric PID. Return targets as [PID, instance_ID] pairs and exited_ancestors
as sorted instance IDs of exited in-scope intermediates that have living
in-scope descendants. No containers, hidden processes or identity uncertainty.
Rows are [instance_ID, PID, start, parent_instance, end].
''' + "\n" + json.dumps(processes),
        {"targets": [[pid, key] for pid, key in targets],
         "exited_ancestors": sorted(key for key, _, start, _, end in processes
                                    if end is not None and end <= 12 and descends(key)
                                    and any(parents.get(livekey) == key for _, livekey in targets))},
        "Original provenance graph: stable process identity prevents PID reuse from expanding containment.")

    headers = [
        ("H1", ["4", "4"], []), ("H2", ["4", "5"], []),
        ("H3", ["4"], ["chunked"]), ("H4", [], ["gzip", "chunked"]),
        ("H5", [], ["chunked", "gzip"]), ("H6", [], []),
        ("H7", ["04", "4"], []), ("H8", ["+4"], []),
    ]
    lengths, chunked, rejected = [], [], []
    for hid, cl, te in headers:
        if (cl and te) or (te and (te[-1] != "chunked" or te.count("chunked") != 1)):
            rejected.append(hid)
        elif te:
            chunked.append(hid)
        elif cl:
            if all(s.isascii() and s.isdecimal() for s in cl) and len({int(s) for s in cl}) == 1:
                lengths.append([hid, int(cl[0])])
            else:
                rejected.append(hid)
        else:
            lengths.append([hid, 0])
    add("cy2-http-framing", "Normalize duplicate lengths while rejecting ambiguous framing", "protocol-security", '''
A defensive HTTP/1.1 gateway receives REQUESTS. All header names are already
case-normalized and all comma lists split; framing fields are represented as
[ID, Content-Length values, Transfer-Encoding codings in order]. No body bytes
or exploit construction are requested. Use this explicit gateway policy:
Reject and close if CL and TE both exist. Otherwise accept TE only if chunked
appears exactly once and is the FINAL coding; gzip decoding is supported.
Without TE, all CL values must be nonempty ASCII decimal digits (leading zeros
allowed) and have the same INTEGER value. Normalize accepted duplicates to one
integer length. No CL and no TE means zero-length REQUEST body.
Return lengths as [ID, integer] pairs for accepted fixed-length requests,
chunked as IDs for accepted TE requests, and reject_close as IDs for rejected
requests. Sort each array by ID. Do not apply response close-delimiting rules.
''' + "\n" + json.dumps(headers),
        {"lengths": lengths, "chunked": chunked, "reject_close": rejected},
        "RFC 9112 framing plus an explicitly stricter reject-both gateway policy.")

    # Compare cache keys to authorization identities; bodies hold tenant labels.
    accesses = [("R1", "GET", "/invoice/7", "red", "en"),
                ("R2", "GET", "/invoice/7", "blue", "en"),
                ("R3", "GET", "/invoice/7", "blue", "fr"),
                ("R4", "GET", "/invoice/7", "red", "fr"),
                ("R5", "GET", "/invoice/8", "red", "en")]
    cache, leaks, hits = {}, [], []
    for rid, method, path, tenant, lang in accesses:
        key = (method, path, lang)
        if key in cache:
            hits.append(rid)
            if cache[key] != tenant:
                leaks.append(rid)
        else:
            cache[key] = tenant
    add("cy2-cache-tenant", "Trace tenant data leakage through an incomplete cache key", "authorization", '''
A gateway authenticates each request and overwrites X-Tenant with the session's
tenant. The origin correctly authorizes and returns a body labeled with that
tenant. A shared cache is checked AFTER authentication but BEFORE origin auth.
Its key is (method, path, Accept-Language). X-Tenant and Cookie are NOT keyed;
responses Vary only on Accept-Language. Every miss stores the tenant-labeled
body; every hit serves that body unchanged. All responses stay fresh for the
entire trace; no other state or invalidation. Requests arrive sequentially.
Return hits (all cache-hit request IDs) and leaked (hits served another tenant's
body), both ascending. Return fixes as alphabetically sorted labels that
prevent cross-tenant reuse without relying on the origin on a cache hit:
A include the trusted session tenant in cache key before lookup and storage
B add HttpOnly to the session cookie
C disable shared caching for this authenticated route, bypass existing entries
D add Vary: Accept-Language a second time
Rows are [ID, method, path, trusted tenant, Accept-Language].
''' + "\n" + json.dumps(accesses),
        {"hits": hits, "leaked": leaks, "fixes": [label for label, safe in [("A", True), ("B", False), ("C", True), ("D", False)] if safe]},
        "RFC 9111 cache selection combined with original authenticated-tenant trace.")

    subjects = [
        ("J1", "sts.amazonaws.com", "repo:acme/pay:ref:refs/heads/main"),
        ("J2", "sts.amazonaws.com", "repo:acme/pay:ref:refs/heads/feature"),
        ("J3", "sts.amazonaws.com", "repo:acme/pay:environment:prod"),
        ("J4", "sts.amazonaws.com", "repo:acme/pay-fork:ref:refs/heads/main"),
        ("J5", "other", "repo:acme/pay:ref:refs/heads/main"),
        ("J6", "sts.amazonaws.com", "repo:acme/pay:pull_request"),
    ]
    exact = {subjects[0][2], subjects[2][2]}
    intended = [jid for jid, aud, sub in subjects if aud == "sts.amazonaws.com" and sub in exact]
    broad = [jid for jid, aud, sub in subjects if aud == "sts.amazonaws.com" and fnmatch.fnmatchcase(sub, "repo:acme/pay:*")]
    add("cy2-oidc-subject", "OIDC trust scopes for branch and environment subject forms", "supply-chain", '''
A GitHub repository was created before July 15, 2026 and still uses the legacy
subject format shown below (it has NOT opted into immutable-ID subjects).
All jobs have valid GitHub signatures and issuer. The intended trust permits
ONLY repo acme/pay on main WITHOUT an environment, OR that exact repository
using environment prod. The deployment platform independently protects prod
environment approval; infer no branch restriction from an environment subject.
All jobs must have aud exactly sts.amazonaws.com. Compare policies:
P checks aud and StringLike sub='repo:acme/pay:*'. Here * matches any suffix.
Q checks aud and StringEquals sub in the TWO intended exact subject values.
Return policy_p, policy_q as accepted job IDs ascending, and excess as IDs P
accepts beyond the intended policy. These are already final literal claims;
do not rewrite them or treat repository name prefixes as the same repository.
Rows are [job ID, aud, sub].
''' + "\n" + json.dumps(subjects),
        {"policy_p": broad, "policy_q": intended, "excess": [jid for jid in broad if jid not in intended]},
        "GitHub OIDC AWS trust documentation; legacy subject format is pinned explicitly.")

    assert len(prompts) == 10
    return {
        "format": "localbench-benchmark", "format_version": "1.0", "exported_at": "",
        "name": "Cyber", "version": "2.0.0",
        "description": "10 original hard defensive-security questions combining policy layers, protocol boundaries, identity provenance, crash consistency and event-time detection. All rules are explicit and JSON answer keys are computed. Difficulty and weights are unmeasured design estimates; no judge required.",
        "tags": ["cyber", "blue-team", "defense", "deterministic"], "scoring_config": {},
        "performance_thresholds": {"desired_ttft": 1.0, "max_ttft": 15.0, "desired_tps": 25.0,
                                   "min_tps": 3.0, "max_failure_rate": 0.1},
        "composite_weights": {"quality": 0.85, "reliability": 0.1, "performance": 0.05}, "prompts": prompts,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if OUT.read_text() != rendered:
            raise SystemExit("Cyber bundle is stale")
    else:
        OUT.write_text(rendered)
    print("Verified Cyber (10 questions)" if args.check else "Wrote Cyber (10 questions)")
