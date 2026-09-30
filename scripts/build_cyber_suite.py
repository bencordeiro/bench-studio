"""Build the defensive Cyber suite and its reference controls, without model calls.

python3 scripts/build_cyber_suite.py [--check]
The scenarios are original. Policy/log answers are computed; vulnerability
classifications use explicit expert keys documented in docs/CYBER_SUITE.md.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import posixpath
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "backend/app/seed/suites/cyber.json"


def build() -> dict:
    prompts = []

    def add(sid, title, category, body, answer, *, difficulty="hard", description):
        types = {bool: "boolean", str: "string", list: "array", int: "integer"}
        fields = ", ".join(f"{key} ({types[type(value)]})" for key, value in answer.items())
        prompts.append({
            "stable_id": sid, "title": title, "description": description,
            "category": f"cyber/{category}", "difficulty": difficulty,
            "tags": ["cyber", "defense", "deterministic", "unmeasured"],
            "importance_weight": 2.0 if difficulty == "hard" else 1.5,
            "position": len(prompts), "enabled": True, "grading_mode": "deterministic",
            "generation_overrides": {"temperature": 0.0},
            "grader_config": {
                "type": "json", "require_valid_json": True, "allow_code_fences": False,
                "allow_extra_fields": False, "expected_field_values": answer, "points": 100.0,
            },
            "messages": [{"role": "user", "position": 0, "content": body.strip()
                          + "\n\nReturn exactly one JSON object with only these fields: " + fields
                          + ". Use the labels and ordering specified above. No explanation or Markdown."}],
        })

    add("cy-tenant-object", "Tenant isolation despite parameterized SQL", "authorization", """
A billing API authenticates users and binds all SQL values as parameters.
Invoice IDs are global. A user may read invoices only in their authenticated
session's tenant. The client can alter invoice_id and the query's tenant value.
Compare these query predicates; there are no other authorization checks:
  A: invoice_id = :request.invoice_id
  B: invoice_id = :request.invoice_id AND tenant = :request.query.tenant
  C: invoice_id = :request.invoice_id AND tenant = :session.tenant
List the vulnerable handlers in alphabetical order. For issue choose one label:
IDOR, SQL_INJECTION, or SSRF. Evaluate authorization, not SQL syntax.
""", {"vulnerable": ["A", "B"], "issue": "IDOR"},
        description="Client-supplied tenant filters do not enforce object authorization; bound SQL is a separate control.")

    add("cy-sql-identifier", "An ORDER BY column is not a bound value", "injection", """
An authorized report query binds its tenant and date filters. Its sort query
parameter is attacker-controlled. Compare these ORDER BY constructions:
  A: append the raw sort string directly to SQL
  B: look up sort in {name: customer_name, created: created_at}; reject unknown
     keys and append only the mapped constant identifier
  C: uppercase the sort string, then append that string directly to SQL
No other escaping or SQL validation occurs. List the vulnerable variants in
alphabetical order. Choose the fix that supports either allowed sort column:
ALLOWLIST_COLUMN_MAP, BIND_IDENTIFIER_AS_VALUE, or UPPERCASE_INPUT.
""", {"vulnerable": ["A", "C"], "fix": "ALLOWLIST_COLUMN_MAP"},
        description="Distinguishes parameterized values from identifiers and rejects cosmetic normalization as protection.")

    add("cy-ssrf-redirect", "A redirect crosses an SSRF allowlist", "request-security", """
A server fetches a user-selected image URL. It accepts HTTPS URLs only at
images.example.test, checks that the initial DNS answers are public, and pins
the connection to a checked address. The initial response redirects to
http://169.254.169.254/latest/meta-data/. The HTTP client follows that redirect
without checking its scheme, hostname or resolved address. There are no
credentials sent to the image server; DNS rebinding on the initial connection
is excluded. Choose issue from SSRF, CSRF, XSS. Choose the complete fix from
VALIDATE_EVERY_REDIRECT_HOP, RECHECK_INITIAL_HOST_ONLY, or HTML_ESCAPE_URL.
The fix must permit redirects that still meet the original destination policy.
""", {"issue": "SSRF", "fix": "VALIDATE_EVERY_REDIRECT_HOP"},
        description="Checks every redirected destination, rather than treating initial URL validation as sufficient.")

    add("cy-csrf-get", "State-changing GET with a Lax session cookie", "request-security", """
A bank authenticates with a Secure, HttpOnly, SameSite=Lax session cookie.
GET /change-payee?account=... changes the current user's payee immediately.
Ownership checks are correct, but there is no CSRF token or Origin check.
A different site can cause a top-level navigation to that HTTPS URL. Assume
Lax sends the cookie on cross-site top-level GET navigations. There is no XSS.
Choose issue from CSRF, IDOR, SESSION_FIXATION and fix from:
POST_WITH_VALIDATED_CSRF_TOKEN, DISABLE_CORS, ADD_HTTPONLY.
The POST fix also removes the mutation from GET; all writes require the token.
""", {"issue": "CSRF", "fix": "POST_WITH_VALIDATED_CSRF_TOKEN"},
        difficulty="medium", description="Separates cookie confidentiality flags and CORS from CSRF prevention.")

    add("cy-dom-text-sink", "Choose a plain-text DOM sink", "injection", """
A profile's display name is untrusted and must be rendered as literal text.
No HTML markup is required. Compare browser assignments:
  A: label.innerHTML = displayName
  B: label.textContent = displayName
  C: label.innerHTML = displayName.replaceAll('"', '&quot;')
No sanitizer or CSP is present. List the unsafe variants in alphabetical order.
Choose the appropriate fix from TEXT_CONTENT, ENCODE_QUOTES_ONLY, EVAL_STRING.
""", {"unsafe": ["A", "C"], "fix": "TEXT_CONTENT"},
        difficulty="medium", description="Tests output context: escaping quotes does not make an HTML text sink safe.")

    root = "/srv/uploads"
    paths = ["/srv/uploads/a.txt", "/srv/uploads_archive/a.txt", "/srv/uploads/team/b.txt"]
    safe = [f"P{i}" for i, path in enumerate(paths, 1) if posixpath.commonpath([root, path]) == root]
    add("cy-path-boundary", "Path containment is not a string prefix", "filesystem", """
A Linux download service resolves paths to canonical absolute paths, then
allows a path whenever path.startswith('/srv/uploads'). Assume no symlinks,
races, bind mounts or ACLs; the issue is the check itself. Candidate paths:
  P1: /srv/uploads/a.txt
  P2: /srv/uploads_archive/a.txt
  P3: /srv/uploads/team/b.txt
Which paths are genuinely inside /srv/uploads? Return their IDs in order.
Choose the repair from COMMONPATH_EQUALS_ROOT, COMMONPREFIX_EQUALS_ROOT,
LOWERCASE_THEN_PREFIX. All inputs to commonpath are canonical absolute paths.
""", {"contained": safe, "fix": "COMMONPATH_EQUALS_ROOT"},
        description="Uses path-component containment and explicitly excludes symlink and race ambiguities.")

    now = 1700000100
    tokens = [
        {"id": "T1", "signature": True, "iss": "corp", "aud": ["reports"], "exp": now + 30, "nbf": now - 1},
        {"id": "T2", "signature": True, "iss": "corp", "aud": ["billing"], "exp": now + 30, "nbf": now - 1},
        {"id": "T3", "signature": True, "iss": "corp", "aud": ["reports"], "exp": now, "nbf": now - 1},
        {"id": "T4", "signature": False, "iss": "corp", "aud": ["reports"], "exp": now + 30, "nbf": now - 1},
        {"id": "T5", "signature": True, "iss": "corp", "aud": ["reports", "billing"], "exp": now + 30, "nbf": now + 1},
        {"id": "T6", "signature": True, "iss": "corp", "aud": ["reports", "billing"], "exp": now + 30, "nbf": now},
    ]
    accepted = [t["id"] for t in tokens if t["signature"] and t["iss"] == "corp"
                and "reports" in t["aud"] and t["nbf"] <= now < t["exp"]]
    add("cy-jwt-claims", "JWT audience and time boundaries", "authentication",
        """At Unix time 1700000100, the reports API accepts a token only if its
signature is valid, iss is corp, aud contains reports, nbf <= now, and now < exp.
No clock skew is allowed. The signature field below is the independently
verified signature result, not an untrusted claim. All other fields are actual
verified claims. Return the accepted token IDs in ascending order.\n\n""" + json.dumps(tokens, indent=2),
        {"accepted": accepted}, description="Combines verified identity, service audience and strict expiration/not-before boundaries.")

    add("cy-tls-hostname", "A trusted certificate for the wrong host", "authentication", """
A client connects to https://payroll.example.test. The leaf certificate is
unexpired, its chain is valid under a trusted CA, and revocation checks pass.
Its DNS subjectAltName is only files.example.test. The client verifies the
chain but has disabled hostname verification. No wildcard or name constraint
is involved. Would complete certificate validation accept this connection?
Return accept as a JSON boolean and missing_check from HOSTNAME_MATCH,
CERTIFICATE_EXPIRY, TRUSTED_CA. Treat the SAN as authoritative for DNS identity.
""", {"accept": False, "missing_check": "HOSTNAME_MATCH"},
        difficulty="medium", description="A trusted certificate chain does not authenticate a different requested hostname.")

    rules = [
        ("DENY", "10.42.0.0/16", "10.0.0.0/8", None),
        ("ALLOW", "10.42.16.0/20", "203.0.113.10/32", 8443),
        ("ALLOW", "10.42.0.0/16", "0.0.0.0/0", 443),
    ]
    flows = [
        ("F1", "10.42.18.9", "203.0.113.10", 8443),
        ("F2", "10.42.32.9", "203.0.113.10", 8443),
        ("F3", "10.42.18.9", "10.9.0.7", 443),
        ("F4", "10.42.32.9", "198.51.100.7", 443),
        ("F5", "10.43.18.9", "198.51.100.7", 443),
    ]
    allowed = []
    for fid, src, dst, port in flows:
        decision = next((action for action, snet, dnet, rport in rules
                         if ipaddress.ip_address(src) in ipaddress.ip_network(snet)
                         and ipaddress.ip_address(dst) in ipaddress.ip_network(dnet)
                         and (rport is None or port == rport)), "DENY")
        if decision == "ALLOW":
            allowed.append(fid)
    add("cy-egress-cidr", "First-match egress rules and subnet boundaries", "network-policy", """
Evaluate NEW TCP flows with this first-match firewall; unmatched traffic is denied.
There is no connection tracking, NAT, DNS or IPv6. Rules in order:
  1. DENY  source 10.42.0.0/16  destination 10.0.0.0/8      any port
  2. ALLOW source 10.42.16.0/20 destination 203.0.113.10/32 port 8443
  3. ALLOW source 10.42.0.0/16  destination 0.0.0.0/0       port 443
Flows (ID, source, destination, destination port):
  F1 10.42.18.9 203.0.113.10 8443
  F2 10.42.32.9 203.0.113.10 8443
  F3 10.42.18.9 10.9.0.7 443
  F4 10.42.32.9 198.51.100.7 443
  F5 10.43.18.9 198.51.100.7 443
Return only the allowed flow IDs in ascending order.
""", {"allowed": allowed}, description="Exercises CIDR membership, specific ports and an earlier internal-address deny.")

    add("cy-iam-deny", "Explicit deny across multiple identity policies", "cloud-policy", """
An AWS IAM role in one account has these identity policies:
  Policy A: Allow s3:GetObject on arn:aws:s3:::ops-logs/*
  Policy B: Deny s3:GetObject on arn:aws:s3:::ops-logs/private/*
  Policy C: Allow s3:GetObject on arn:aws:s3:::ops-logs/private/incident.json
There are no other policies, resource policies, conditions, ACL grants, SCPs,
permissions boundaries, session policies or additional service restrictions.
Evaluate these requests (ID, action, resource):
  R1 GetObject ops-logs/public/a.json
  R2 GetObject ops-logs/private/incident.json
  R3 GetObject ops-logs/private/archive.json
  R4 PutObject ops-logs/public/a.json
  R5 GetObject ops-logs/archive/b.json
All resources above refer to their usual S3 object ARNs. Return allowed request
IDs in ascending order and the decisive rule for R2 from EXPLICIT_DENY,
LAST_POLICY_WINS, MORE_SPECIFIC_ALLOW.
""", {"allowed": ["R1", "R5"], "r2_rule": "EXPLICIT_DENY"},
        description="A more specific allow cannot override an applicable explicit deny; absent allows remain denied.")

    add("cy-linux-directory", "A protected file in a writable directory", "host-hardening", """
On a Linux filesystem, a root service reopens /etc/agent/agent.conf by pathname
every minute. /etc/agent is owned by root:developers with mode 0775; the regular
config file is owned by root:root with mode 0644. User alex is in developers.
All ancestor directories are searchable by alex.
There is no sticky bit, immutable flag, ACL, SELinux/AppArmor restriction,
read-only mount, symlink or integrity check. Alex cannot write the existing
file's contents. Can alex nevertheless replace the directory entry with a
new file? Return can_replace as a JSON boolean and the corrective permission
change from REMOVE_GROUP_DIRECTORY_WRITE, REMOVE_FILE_OTHER_READ,
ADD_FILE_OWNER_WRITE. Preserve the service's ability to read the configuration.
""", {"can_replace": True, "fix": "REMOVE_GROUP_DIRECTORY_WRITE"},
        description="Replacement depends on directory write/search permissions, not the existing file's write bits.")

    add("cy-container-volume", "Read-only root versus writable mounted volumes", "host-hardening", """
A Kubernetes container has readOnlyRootFilesystem: true. Its only mounted
volume is an emptyDir at /work with volumeMount.readOnly: false. UID 1000 owns
/work with mode 0700, and the application runs as UID 1000. /etc and /tmp are
ordinary directories in the root filesystem, not mounts or symlinks. Ignore
disk exhaustion, MAC policies and capabilities; no other filesystems are mounted.
Which new file paths can the application create? Return IDs in order:
  P1 /etc/new.conf
  P2 /work/cache.bin
  P3 /tmp/new.log
""", {"writable": ["P2"]}, description="A read-only container root does not make a separately mounted writable volume read-only.")

    add("cy-gcm-nonce", "Counter reset under a persistent GCM key", "cryptography", """
A service uses AES-GCM with a persistent key K and a 96-bit counter nonce.
The nonce increments per message but is held only in memory. After a restart
the counter returns to zero while K remains unchanged, and different new
plaintexts are encrypted with nonce values used before the restart.
Choose issue from GCM_NONCE_REUSE, WEAK_KEY_LENGTH, MISSING_PASSWORD_SALT.
List affected guarantees in alphabetical order from confidentiality, integrity.
Choose fix from PERSIST_COUNTER_OR_ROTATE_KEY, INCREASE_TAG_LENGTH,
BASE64_ENCODE_CIPHERTEXT. Assume the counter never wraps and only one instance
uses K; a persistent counter is reserved durably before each encryption.
""", {"issue": "GCM_NONCE_REUSE", "affected": ["confidentiality", "integrity"],
        "fix": "PERSIST_COUNTER_OR_ROTATE_KEY"},
        description="Nonce uniqueness is per key; restarting a process does not reset the cryptographic requirement.")

    add("cy-password-storage", "Salted fast hashes and adaptive password storage", "cryptography", """
A database stores each password as one SHA-256 hash with a fresh random per-user
salt. The database can be stolen, exposing salts and hashes. The company requires
a deliberately expensive memory-hard password KDF for new records.
Candidate replacements, all with independent random per-user salts:
  A: SHA-256, one iteration
  B: Argon2id, 64 MiB memory, 3 iterations, parallelism 1
  C: reversible AES encryption using a key stored alongside the database
Choose the suitable replacement's ID and the weakness of the original from
FAST_OFFLINE_GUESSING, SALT_COLLISION, SQL_INJECTION. Assume B has passed the
service's resource/load tests and the hash implementation is otherwise correct.
""", {"replacement": "B", "issue": "FAST_OFFLINE_GUESSING"},
        difficulty="medium", description="Salts defeat shared precomputation but do not add the cost of a password KDF.")

    # Synthetic minute offsets avoid clock/time-zone dependencies. The left
    # window boundary is open, so a failure at minute 0 is excluded at minute 5.
    events = [
        (0, "203.0.113.60", "a", "fail"), (1, "203.0.113.60", "b", "fail"),
        (2, "203.0.113.60", "c", "fail"), (3, "203.0.113.60", "d", "fail"),
        (4, "203.0.113.60", "e", "fail"),
        (1, "203.0.113.61", "a", "fail"), (2, "203.0.113.61", "b", "fail"),
        (3, "203.0.113.61", "c", "fail"), (4, "203.0.113.61", "d", "fail"),
        (5, "203.0.113.61", "e", "fail"),
        (2, "203.0.113.62", "a", "fail"), (3, "203.0.113.62", "a", "fail"),
        (4, "203.0.113.62", "b", "success"), (5, "203.0.113.62", "c", "fail"),
    ]
    users = defaultdict(set)
    for minute, address, user, result in events:
        if 0 < minute <= 5 and result == "fail":
            users[address].add(user)
    alerts = sorted(address for address, accounts in users.items() if len(accounts) >= 5)
    table = "\n".join(f"12:{minute:02}:00 {address} {user} {result}" for minute, address, user, result in events)
    add("cy-alert-window", "Password-spray alert with a distinct-user threshold", "detection", """
At 12:05:00 UTC, alert on each source IP with failed logins for at least five
DISTINCT usernames in the window (12:00:00, 12:05:00]. Include the right boundary
and exclude the left boundary. Count only result=fail, not successes; repeated
failures for the same username count once. All entries are on the same day.
Return alert_ips in ascending textual order. Log columns: time, IP, user, result.
\n""" + table, {"alert_ips": alerts},
        description="Combines a time-window boundary, failure filtering and distinct accounts rather than raw event count.")

    processes = [(100, 1, "web"), (110, 100, "python"), (120, 110, "sh"),
                 (130, 120, "curl"), (200, 1, "cron"), (210, 200, "sh"), (220, 210, "backup")]
    chain = {100}
    while True:
        expanded = chain | {pid for pid, parent, _ in processes if parent in chain}
        if expanded == chain:
            break
        chain = expanded
    add("cy-process-lineage", "Scope containment by process ancestry", "incident-response", """
EDR has confirmed process 100 on web-02 was compromised. The containment playbook
requires terminating that process and ALL of its current descendants, while
leaving unrelated process trees intact. This is a complete process snapshot;
there is no PID reuse, reparenting or already-exited process. Do not terminate
ancestors. Return terminate_pids as JSON integers in ascending numerical order.
Columns below: PID, parent PID, executable.\n\n"""
        + "\n".join(f"{pid} {parent} {exe}" for pid, parent, exe in processes),
        {"terminate_pids": sorted(chain)},
        description="Builds the complete containment scope without treating an unrelated shell as part of the incident.")

    assets = [
        {"id": "V1", "reachable": True, "known_exploited": False, "cvss": 9.8},
        {"id": "V2", "reachable": False, "known_exploited": False, "cvss": 7.0},
        {"id": "V3", "reachable": True, "known_exploited": True, "cvss": 8.1},
        {"id": "V4", "reachable": False, "known_exploited": True, "cvss": 9.4},
    ]
    ordered = sorted(assets, key=lambda a: (not (a["reachable"] and a["known_exploited"]), -a["cvss"], a["id"]))
    add("cy-patch-priority", "Exposure and exploitation outrank raw CVSS", "vulnerability-management", """
All four findings are confirmed, affected, unpatched, and have deployable fixes.
Use this organization's deterministic patch ordering: first, findings BOTH
externally reachable and known exploited; then all other findings. Within each
group, order by descending CVSS, then ascending ID for ties. Flags below are
verified inventory facts, not a request to look up current CVEs. Return priority
as the complete ordered list of finding IDs.\n\n""" + json.dumps(assets, indent=2),
        {"priority": [a["id"] for a in ordered]},
        description="Applies a stated defensive triage policy; priority is not an unstated subjective judgment.")

    add("cy-http-framing", "Different HTTP message boundaries at two hops", "protocol-security", """
An HTTP/1.1 reverse proxy and backend reuse the same persistent upstream
connection. Requests containing BOTH Content-Length and Transfer-Encoding are
forwarded unchanged. The proxy uses Content-Length to locate the request end;
the backend uses chunked Transfer-Encoding. Assume neither rejects the request
and the two interpretations can yield different boundaries.
Choose issue from HTTP_REQUEST_SMUGGLING, CSRF, CERTIFICATE_EXPIRY. Choose the
defensive fix from REJECT_AMBIGUOUS_FRAMING_AND_CLOSE, ADD_COOKIE_HTTPONLY,
ALLOW_BOTH_HEADERS_UNCHANGED. The reject fix occurs before forwarding.
""", {"issue": "HTTP_REQUEST_SMUGGLING", "fix": "REJECT_AMBIGUOUS_FRAMING_AND_CLOSE"},
        description="Detects framing disagreement across a proxy boundary without constructing an exploit request.")

    assert len(prompts) == 18
    assert len({p["stable_id"] for p in prompts}) == len(prompts)
    return {
        "format": "localbench-benchmark", "format_version": "1.0",
        "exported_at": "2026-09-29T00:00:00+00:00", "name": "Cyber", "version": "1.0.0",
        "description": "18 original deterministic defensive-security scenarios: vulnerability identification, "
                       "authorization, browser and HTTP security, cryptography, cloud and network policy, "
                       "host hardening, alert analysis, containment and patch triage. "
                       "All answers are closed-schema JSON; no judge, tools or code execution required. "
                       "Difficulty and weights are design estimates, not model-calibrated results.",
        "tags": ["cyber", "blue-team", "defense", "deterministic"], "scoring_config": {},
        "performance_thresholds": {"desired_ttft": 1.0, "max_ttft": 15.0, "desired_tps": 25.0,
                                   "min_tps": 3.0, "max_failure_rate": 0.1},
        "composite_weights": {"quality": 0.85, "reliability": 0.1, "performance": 0.05},
        "prompts": prompts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Cyber bundle is stale; run scripts/build_cyber_suite.py")
    else:
        OUT.write_text(rendered, encoding="utf-8")
    print(f"{'Verified' if args.check else 'Wrote'} {OUT.relative_to(REPO)} (18 questions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
