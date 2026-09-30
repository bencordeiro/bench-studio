"""Independent evidence for every terminal answer (no privileged/network actions)."""

import calendar
import ipaddress
import json
import shutil
import sqlite3
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from app.graders.deterministic import run_deterministic
from app.seed.suites_loader import SUITES_DIR

PROMPTS = {
    p["stable_id"]: p for p in json.loads((SUITES_DIR / "terminal_semantics.json").read_text())["prompts"]
}


def answer(sid):
    return PROMPTS[sid]["grader_config"]["canonical_answer"]


def shell(code, cwd):
    proc = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_acl_mask(tmp_path):
    if not shutil.which("setfacl"):
        pytest.skip("POSIX ACL tools unavailable")
    probe = tmp_path / "probe"
    probe.touch()
    supported = subprocess.run(["setfacl", "-m", "u:1042:rwx", str(probe)], capture_output=True, text=True)
    if supported.returncode:
        if "Invalid argument" in supported.stderr or "not supported" in supported.stderr:
            pytest.skip("test filesystem does not support POSIX ACLs")
        pytest.fail(supported.stderr)
    output = shell(
        "mkdir data; chmod 0754 data; setfacl -m u:1042:rwx,g:2088:rx,other::--- data; setfacl -d -m u:1042:rX,g:2088:rX data; stat -c %a data; chmod 0754 data; stat -c %a data; getfacl -cn data",
        tmp_path,
    )
    lines = output.splitlines()
    assert ",".join(lines[:2]) == ",".join(answer("ts-perm-mask").split(",")[:2])
    assert "user:1042:rwx\t#effective:r-x" in lines


def test_git_reachability(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git unavailable")
    code = """git init -q
 git -c user.name=T -c user.email=t@test -c core.hooksPath=/dev/null commit --allow-empty -qm A
 git -c user.name=T -c user.email=t@test -c core.hooksPath=/dev/null commit --allow-empty -qm B
 git -c user.name=T -c user.email=t@test -c core.hooksPath=/dev/null commit --allow-empty -qm C
 git tag saved
 git reset --hard HEAD~1 >/dev/null
 git -c user.name=T -c user.email=t@test -c core.hooksPath=/dev/null commit --allow-empty -qm D
 git rev-list --count HEAD
 git rev-list --count saved
 git rev-list --count HEAD..saved"""
    assert ",".join(shell(code, tmp_path).splitlines()) == answer("ts-git-forensics")


def test_date_order():
    times = {
        "A": datetime(2026, 3, 8, 1, 45, tzinfo=timezone.utc),
        "B": datetime(2026, 3, 7, 21, 30, tzinfo=timezone(timedelta(hours=-5))),
        "C": datetime(2026, 3, 8, 7, tzinfo=timezone(timedelta(hours=-4))),
        "D": datetime(2026, 3, 7, 23, 45, tzinfo=timezone.utc),
        "E": datetime(2026, 3, 8, 1, 30, tzinfo=timezone(timedelta(hours=1))),
        "F": datetime.fromtimestamp(1772938800, timezone.utc),
        "G": datetime(2026, 3, 7, 22, 25, tzinfo=timezone(timedelta(hours=-5))),
    }
    assert ",".join(sorted(times, key=times.get)) == answer("ts-date-normalization")


def test_log_aggregation():
    text = PROMPTS["ts-log-aggregation"]["messages"][-1]["content"]
    counts = Counter()
    for line in text.splitlines():
        if " - - [" not in line:
            continue
        ip = line.split()[0].lower().removeprefix("::ffff:")
        if ":" not in ip:
            ip = ".".join(str(int(part)) for part in ip.split("."))
        counts[ip] += 1
    ip, count = counts.most_common(1)[0]
    assert f"{ip} {count}" == answer("ts-log-aggregation")


def test_sed_range(tmp_path):
    if not shutil.which("sed"):
        pytest.skip("sed unavailable")
    text = PROMPTS["ts-html-sed"]["messages"][-1]["content"]
    html = text.split("\n", 1)[1].split("\n\nYou run:", 1)[0]
    (tmp_path / "page.html").write_text(html + "\n")
    assert shell("sed -n '/<script/,/<\\/script>/p' page.html | wc -l", tmp_path) == answer("ts-html-sed")
    # The ending regexp isn't tested on the opening line. A literal closing
    # tag inside a JS string is still a match: sed does not parse HTML or JS.
    selected = shell("sed -n '/<script/,/<\\/script>/=' page.html", tmp_path)
    assert list(map(int, selected.splitlines())) == [*range(6, 12), *range(13, 17), 19, 20, 21]


def test_wal_snapshot(tmp_path):
    path = tmp_path / "snapshot.db"
    with sqlite3.connect(path) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE t(v INTEGER)")
        setup.execute("INSERT INTO t VALUES (10)")
    r = sqlite3.connect(path)
    w = sqlite3.connect(path)
    try:
        r.execute("BEGIN")
        values = [r.execute("SELECT sum(v) FROM t").fetchone()[0]]
        w.execute("BEGIN")
        w.execute("INSERT INTO t VALUES (20)")
        w.commit()
        values.append(r.execute("SELECT sum(v) FROM t").fetchone()[0])
        r.commit()
        values.append(r.execute("SELECT sum(v) FROM t").fetchone()[0])
        assert ",".join(map(str, values)) == answer("ts-sqlite-wal")
    finally:
        r.close()
        w.close()


def test_cron_or_day_fields():
    days = sum(day in (1, 15) or calendar.weekday(2026, 3, day) < 5 for day in range(1, 32))
    assert str(days) == answer("ts-cron-firing")


def test_pipeline_snapshot(tmp_path):
    assert shell(
        'set +e\nset -o pipefail\n(exit 7) | (exit 3) | true\nprintf "%s|%s\\n" "$?" "${PIPESTATUS[*]}"',
        tmp_path,
    ) == answer("ts-bash-pipefail")


def test_dependency_relaxation():
    # Independently enumerate the four proposed single-pin replacements.
    variants = {
        "A": (2.4, 2.0, 1.12, 1.26),
        "B": (2.3, 2.0, 1.12, 1.26),
        "C": (2.4, 2.0, 1.11, 1.26),
        "D": (2.4, 1.5, 1.12, 1.26),
    }

    def valid(v):
        df, pd, sp, np = v
        return (
            ((df == 2.4 and pd >= 2 and sp < 1.12) or (df == 2.3 and 1.5 <= pd < 2))
            and (sp != 1.11 or np < 1.27)
            and (sp != 1.12 or np >= 1.26)
            and (pd != 2 or np >= 1.26)
        )

    assert [key for key, v in variants.items() if valid(v)] == [
        PROMPTS["ts-conda-conflict"]["grader_config"]["correct_option"]
    ]


def test_locale_and_find(tmp_path):
    tmp_path = tmp_path / "filenames"
    tmp_path.mkdir()
    names = ["!bang.txt", "10.txt", "2.txt", "Apple.txt", "Zebra.txt", "apple.txt", "zzz.txt", ".hidden"]
    for name in names:
        (tmp_path / name).touch()
    assert ",".join(shell("LC_ALL=C QUOTING_STYLE=literal ls -1", tmp_path).splitlines()) == answer(
        "ts-sort-locale"
    )
    other = tmp_path / "find-case"
    other.mkdir()
    for name in ["a.txt", "b.log", "c.txt", "d data.txt", " -e.txt"]:
        (other / name).touch()
    assert shell("find . -type f -name '*.txt' | LC_ALL=C sort | wc -l", other) == answer("ts-find-xargs")


def test_firewall_rules():
    packets = [
        ("tcp", 22, "192.0.2.1"),
        ("tcp", 80, "192.0.2.1"),
        ("tcp", 22, "10.1.2.3"),
        ("tcp", 443, "192.0.2.1"),
        ("udp", 53, "10.1.2.3"),
        ("tcp", 443, "10.1.2.3"),
    ]
    rules = [
        lambda p: p[0] == "tcp" and p[1] == 80,
        lambda p: p[0] == "tcp" and p[1] == 22,
        lambda p: ipaddress.ip_address(p[2]) in ipaddress.ip_network("10.0.0.0/8"),
        lambda p: p[0] == "tcp" and p[1] == 443,
    ]
    accepted = [str(i) for i, p in enumerate(packets, 1) if any(rule(p) for rule in rules)]
    assert ",".join(accepted) == answer("ts-iptables-filter")


def test_acl_mode_and_effective_permissions_by_rule():
    # setfacl recalculates mask as union of owning group and all named entries.
    owner, group, named_user, named_group, other = 7, 5, 7, 5, 0
    mask = group | named_user | named_group
    mode_before = f"{owner}{mask}{other}"
    # chmod 0754 sets owner=7, mask=5, other=4 without removing the named user.
    effective = named_user & 5
    assert f"{mode_before},754,{ {5: 'r-x'}[effective] }" == answer("ts-perm-mask")


@pytest.mark.parametrize("sid", ["ts-git-forensics", "ts-sqlite-wal"])
def test_three_result_answers_accept_comma_spacing_but_reject_wrong_values(sid):
    config = PROMPTS[sid]["grader_config"]
    values = answer(sid).split(",")
    for first in (",", ", ", ",\t"):
        for second in (",", ", ", ",\t"):
            response = f"Explanation.\nANSWER: {values[0]}{first}{values[1]}{second}{values[2]}"
            assert run_deterministic(config, response)["score"] == 100
    for wrong in ([values[0], values[1], "999"], values[:2], values + ["0"]):
        assert not run_deterministic(config, "ANSWER: " + ", ".join(wrong))["passed"]
