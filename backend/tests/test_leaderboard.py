"""Leaderboard: opt-in flag, model grouping, scoring basis, sorting."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _make_suite(c: TestClient, name: str = "Suite", show: bool = False) -> str:
    r = c.post("/api/benchmarks", json={"name": name, "show_in_leaderboards": show})
    assert r.status_code == 201
    return r.json()["id"]


def _add_run(
    benchmark_id: str,
    model: str,
    *,
    status: str = "completed",
    quality: float | None = None,
    reliability: float | None = None,
    performance: float | None = None,
    composite: float | None = None,
    version: str = "1.0.0",
    endpoint: str = "Local",
    when: datetime | None = None,
) -> str:
    from app.db.session import session_scope
    from app.models import BenchmarkRun

    with session_scope() as s:
        run = BenchmarkRun(
            id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            target_model=model,
            target_endpoint_name=endpoint,
            status=status,
            benchmark_snapshot={"version": version, "name": "snap"},
            summary={
                "quality_score": quality,
                "reliability_score": reliability,
                "performance_index": performance,
                "composite_score": composite,
            },
            completed_at=when,
        )
        s.add(run)
        return run.id


# --------------------------------------------------------------------------- #
# Opt-in flag
# --------------------------------------------------------------------------- #
def test_flag_defaults_off(temp_data_dir):
    with _client() as c:
        r = c.post("/api/benchmarks", json={"name": "NoFlag"})
        assert r.status_code == 201
        assert r.json()["show_in_leaderboards"] is False
        bid = r.json()["id"]
        assert c.get(f"/api/benchmarks/{bid}").json()["show_in_leaderboards"] is False
        summary = next(b for b in c.get("/api/benchmarks").json() if b["id"] == bid)
        assert summary["show_in_leaderboards"] is False


def test_flag_toggle_persists_on_update(temp_data_dir):
    with _client() as c:
        bid = _make_suite(c, "Toggle", show=False)
        # PUT the full body with the flag flipped on.
        r = c.put(f"/api/benchmarks/{bid}", json={"name": "Toggle", "show_in_leaderboards": True})
        assert r.status_code == 200
        assert r.json()["show_in_leaderboards"] is True
        assert c.get(f"/api/benchmarks/{bid}").json()["show_in_leaderboards"] is True


def test_duplicate_resets_flag(temp_data_dir):
    with _client() as c:
        bid = _make_suite(c, "Original", show=True)
        dup = c.post(f"/api/benchmarks/{bid}/duplicate")
        assert dup.status_code == 200
        assert dup.json()["show_in_leaderboards"] is False


# --------------------------------------------------------------------------- #
# Picker: only opted-in suites appear
# --------------------------------------------------------------------------- #
def test_only_optin_suites_listed(temp_data_dir):
    with _client() as c:
        shown = _make_suite(c, "Shown", show=True)
        hidden = _make_suite(c, "Hidden", show=False)
        _add_run(shown, "gpt", quality=90)
        _add_run(hidden, "gpt", quality=90)

        listed = c.get("/api/leaderboards").json()
        ids = {s["suite_id"] for s in listed}
        assert shown in ids
        assert hidden not in ids
        entry = next(s for s in listed if s["suite_id"] == shown)
        assert entry["run_count"] == 1
        assert entry["model_count"] == 1
        assert entry["top_model"] == "gpt"
        assert entry["top_quality_score"] == 90


# --------------------------------------------------------------------------- #
# Grouping + status filtering
# --------------------------------------------------------------------------- #
def test_groups_by_model_and_counts_runs(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Grouping", show=True)
        _add_run(suite, "model-a", quality=80)
        _add_run(suite, "model-a", quality=90)
        _add_run(suite, "model-b", quality=70)

        board = c.get(f"/api/leaderboards/{suite}").json()
        assert board["total_runs"] == 3
        by_model = {e["model"]: e for e in board["entries"]}
        assert set(by_model) == {"model-a", "model-b"}
        assert by_model["model-a"]["run_count"] == 2
        assert len(by_model["model-a"]["run_ids"]) == 2


def test_only_completed_runs_counted(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Statuses", show=True)
        _add_run(suite, "gpt", status="completed", quality=80)
        _add_run(suite, "gpt", status="completed_with_errors", quality=60)
        _add_run(suite, "gpt", status="queued", quality=100)
        _add_run(suite, "gpt", status="failed", quality=100)
        _add_run(suite, "gpt", status="running_target", quality=100)

        board = c.get(f"/api/leaderboards/{suite}").json()
        assert board["total_runs"] == 2
        assert board["entries"][0]["run_count"] == 2


# --------------------------------------------------------------------------- #
# Scoring basis
# --------------------------------------------------------------------------- #
def test_basis_best_mean_latest(temp_data_dir):
    now = datetime.now(timezone.utc)
    with _client() as c:
        suite = _make_suite(c, "Basis", show=True)
        _add_run(suite, "gpt", quality=60, when=now - timedelta(hours=2))
        _add_run(suite, "gpt", quality=90, when=now - timedelta(hours=1))
        _add_run(suite, "gpt", quality=30, when=now)  # latest = 30

        best = c.get(f"/api/leaderboards/{suite}?basis=best").json()["entries"][0]
        assert best["quality_score"] == 90
        mean = c.get(f"/api/leaderboards/{suite}?basis=mean").json()["entries"][0]
        assert mean["quality_score"] == 60  # (60+90+30)/3
        latest = c.get(f"/api/leaderboards/{suite}?basis=latest").json()["entries"][0]
        assert latest["quality_score"] == 30


def test_missing_metric_ignored_for_best_and_mean(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Missing", show=True)
        _add_run(suite, "gpt", quality=80)
        _add_run(suite, "gpt", quality=None)  # e.g. all-manual run

        best = c.get(f"/api/leaderboards/{suite}?basis=best").json()["entries"][0]
        assert best["quality_score"] == 80
        mean = c.get(f"/api/leaderboards/{suite}?basis=mean").json()["entries"][0]
        assert mean["quality_score"] == 80  # None excluded from the average


# --------------------------------------------------------------------------- #
# Sorting + ranking
# --------------------------------------------------------------------------- #
def test_sort_by_quality_default_then_performance(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Sorting", show=True)
        _add_run(suite, "fast-but-dumb", quality=40, performance=95)
        _add_run(suite, "slow-but-smart", quality=95, performance=40)

        by_quality = c.get(f"/api/leaderboards/{suite}").json()
        assert by_quality["sort_metric"] == "quality"
        assert [e["model"] for e in by_quality["entries"]] == ["slow-but-smart", "fast-but-dumb"]
        assert by_quality["entries"][0]["rank"] == 1
        assert by_quality["entries"][1]["rank"] == 2

        by_perf = c.get(f"/api/leaderboards/{suite}?sort=performance").json()
        assert [e["model"] for e in by_perf["entries"]] == ["fast-but-dumb", "slow-but-smart"]


def test_none_metric_sorts_last(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Nones", show=True)
        _add_run(suite, "scored", quality=50)
        _add_run(suite, "unscored", quality=None)

        entries = c.get(f"/api/leaderboards/{suite}").json()["entries"]
        assert entries[0]["model"] == "scored"
        assert entries[1]["model"] == "unscored"
        assert entries[1]["quality_score"] is None


def test_version_mismatch_warning(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Versions", show=True)
        _add_run(suite, "gpt", quality=80, version="1.0.0")
        _add_run(suite, "gpt", quality=80, version="2.0.0")

        board = c.get(f"/api/leaderboards/{suite}").json()
        assert any("different benchmark versions" in w for w in board["warnings"])


def test_invalid_basis_and_sort_rejected(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Invalid", show=True)
        assert c.get(f"/api/leaderboards/{suite}?basis=bogus").status_code == 400
        assert c.get(f"/api/leaderboards/{suite}?sort=bogus").status_code == 400


def test_unknown_suite_404(temp_data_dir):
    with _client() as c:
        assert c.get("/api/leaderboards/does-not-exist").status_code == 404


# --------------------------------------------------------------------------- #
# Review fixes
# --------------------------------------------------------------------------- #
def test_representative_run_is_basis_aware(temp_data_dir):
    now = datetime.now(timezone.utc)
    with _client() as c:
        suite = _make_suite(c, "Representative", show=True)
        best_run = _add_run(suite, "gpt", quality=95, when=now - timedelta(hours=2))
        latest_run = _add_run(suite, "gpt", quality=40, when=now)

        best = c.get(f"/api/leaderboards/{suite}?basis=best").json()["entries"][0]
        assert best["representative_run_id"] == best_run  # run that produced the 95
        latest = c.get(f"/api/leaderboards/{suite}?basis=latest").json()["entries"][0]
        assert latest["representative_run_id"] == latest_run


def test_outdated_suite_version_warning(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Outdated", show=True)
        _add_run(suite, "gpt", quality=80, version="0.9.0")  # suite itself is 1.0.0

        board = c.get(f"/api/leaderboards/{suite}").json()
        assert any("since changed" in w for w in board["warnings"])


def test_non_numeric_summary_value_skipped(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Corrupt", show=True)
        _add_run(suite, "gpt", quality=80)
        # Simulate a legacy/corrupt run whose summary holds a non-numeric value.
        import uuid as _uuid

        from app.db.session import session_scope
        from app.models import BenchmarkRun

        with session_scope() as s:
            s.add(BenchmarkRun(
                id=str(_uuid.uuid4()), benchmark_id=suite, target_model="gpt",
                status="completed", benchmark_snapshot={"version": "1.0.0"},
                summary={"quality_score": "N/A"},
            ))

        r = c.get(f"/api/leaderboards/{suite}")
        assert r.status_code == 200  # corrupt value skipped, not a 500
        assert r.json()["entries"][0]["quality_score"] == 80


def test_manual_grade_updates_run_summary(temp_data_dir):
    """POST /executions/{id}/manual must recompute run.summary (leaderboards read it)."""
    import uuid as _uuid

    from app.db.session import session_scope
    from app.models import BenchmarkRun, PromptExecution

    with _client() as c:
        suite = _make_suite(c, "ManualGrade", show=True)
        run_id = _add_run(suite, "gpt", quality=None)
        exec_id = str(_uuid.uuid4())
        with session_scope() as s:
            s.add(PromptExecution(
                id=exec_id, run_id=run_id, prompt_snapshot_id="p1",
                status="awaiting_manual",
                prompt_snapshot={"title": "Manual", "importance_weight": 1.0,
                                 "grading_mode": "manual", "category": "general"},
            ))

        r = c.post(f"/api/runs/executions/{exec_id}/manual",
                   json={"score": 88, "notes": "good"})
        assert r.status_code == 200

        with session_scope() as s:
            summary = s.get(BenchmarkRun, run_id).summary or {}
        assert summary.get("quality_score") == 88

        board = c.get(f"/api/leaderboards/{suite}").json()
        assert board["entries"][0]["quality_score"] == 88


def test_last_run_at_has_utc_offset(temp_data_dir):
    with _client() as c:
        suite = _make_suite(c, "Timezone", show=True)
        _add_run(suite, "gpt", quality=80, when=datetime.now(timezone.utc))

        entry = c.get(f"/api/leaderboards/{suite}").json()["entries"][0]
        assert entry["last_run_at"] is not None
        assert entry["last_run_at"].endswith("+00:00") or entry["last_run_at"].endswith("Z")
