"""The Index requires complete suite coverage and keeps suite contributions equal."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.models import BenchmarkRun, BenchmarkSet
from app.schemas.settings import DEFAULT_INDEX_SUITE_NAMES


def _suites(session):
    suites = [BenchmarkSet(id=str(uuid.uuid4()), name=name, version="1.0.0") for name in DEFAULT_INDEX_SUITE_NAMES]
    session.add_all(suites)
    session.flush()
    return [s.id for s in suites]


def _run(session, suite_id, model, score, *, status="completed", day=0, scored=1, total=1):
    run = BenchmarkRun(id=str(uuid.uuid4()), benchmark_id=suite_id, target_model=model,
                       status=status, target_endpoint_name="Local", benchmark_snapshot={"version": "1.0.0"},
                       completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day),
                       summary={"quality_score": score, "scored_count": scored, "total_count": total})
    session.add(run)
    session.flush()
    return run.id


def _client():
    from app.main import app
    return TestClient(app)


def test_exact_seven_defaults_and_only_fully_completed_models(session):
    ids = _suites(session)
    extras = [BenchmarkSet(id=str(uuid.uuid4()), name=name, version="1.0.0")
              for name in ("Master Suite", "HumanEval (OpenAI)")]
    session.add_all(extras)
    session.flush()
    for i, sid in enumerate(ids):
        _run(session, sid, "balanced", 60)
        _run(session, sid, "uneven", [90, 70, 60, 50, 40, 30, 20][i])
        _run(session, sid, "completed-errors", 0 if i == 6 else 100,
             status="completed_with_errors" if i == 6 else "completed")
        _run(session, sid, "zero", 0, status="completed_with_errors")
        _run(session, sid, "not-complete", 100, status="cancelled" if i == 6 else "completed")
        _run(session, sid, "grading-pending", 100, scored=0 if i == 6 else 1)
    _run(session, ids[0], "one-suite-winner", 100)
    for extra in extras:
        _run(session, extra.id, "unselected-winner", 100)
    session.commit()
    with _client() as c:
        board = c.get("/api/index").json()
        assert [s["name"] for s in board["suites"]] == list(DEFAULT_INDEX_SUITE_NAMES)
        assert [e["model"] for e in board["entries"]] == ["completed-errors", "balanced", "uneven", "zero"]
        assert [e["index_score"] for e in board["entries"]] == [85.71, 60, 51.43, 0]
        assert all(e["completed_suites"] == 7 and e["required_suites"] == 7 for e in board["entries"])
        assert board["incomplete_model_count"] == 3
        assert c.get("/api/index?basis=invalid").status_code == 400
        assert len(c.get("/api/index/config").json()["default_suite_ids"]) == 7


def test_settings_membership_persists_and_recomputes_existing_runs(session):
    ids = _suites(session)
    _run(session, ids[0], "two-suites", 80)
    _run(session, ids[1], "two-suites", 60)
    session.commit()
    with _client() as c:
        assert c.get("/api/index").json()["entries"] == []
        settings = c.get("/api/settings").json()
        settings["index_suite_ids"] = ids[:2]
        assert c.put("/api/settings", json=settings).status_code == 200
        assert c.get("/api/index").json()["entries"][0]["index_score"] == 70
        # An older client omitting the new field must not reset it.
        settings.pop("index_suite_ids")
        settings["default_max_tokens"] = 8192
        assert c.put("/api/settings", json=settings).status_code == 200
        assert c.get("/api/settings").json()["index_suite_ids"] == ids[:2]
    with _client() as c:
        assert c.get("/api/settings").json()["index_suite_ids"] == ids[:2]
        assert c.get("/api/index").json()["entries"][0]["model"] == "two-suites"
        settings = c.get("/api/settings").json()
        settings["index_suite_ids"] = None
        c.put("/api/settings", json=settings)
        assert len(c.get("/api/index").json()["suites"]) == 7
        assert c.get("/api/index").json()["entries"] == []


def test_basis_is_per_suite_not_per_run_and_zero_counts(session):
    ids = _suites(session)
    _run(session, ids[0], "model", 100, day=0)
    latest = _run(session, ids[0], "model", 0, day=1, status="completed_with_errors")
    second = _run(session, ids[1], "model", 80)
    session.commit()
    with _client() as c:
        settings = c.get("/api/settings").json()
        settings["index_suite_ids"] = ids[:2]
        c.put("/api/settings", json=settings)
        for basis, expected in (("latest", 40), ("best", 90), ("mean", 65)):
            entry = c.get(f"/api/index?basis={basis}").json()["entries"][0]
            assert entry["index_score"] == expected
            assert entry["run_count"] == 3
            assert entry["suite_scores"][1]["representative_run_id"] == second
            if basis == "latest":
                assert entry["suite_scores"][0]["representative_run_id"] == latest


def test_missing_suite_is_not_silently_removed_from_required_coverage(session):
    ids = _suites(session)
    for sid in ids:
        _run(session, sid, "model", 100)
    session.commit()
    with _client() as c:
        settings = c.get("/api/settings").json()
        settings["index_suite_ids"] = [ids[0], "deleted-suite"]
        c.put("/api/settings", json=settings)
        board = c.get("/api/index").json()
        assert len(board["suites"]) == 2
        assert board["suites"][1]["missing"]
        assert board["entries"] == []
        assert any("missing" in w for w in board["warnings"])
        settings["index_suite_ids"] = []
        c.put("/api/settings", json=settings)
        assert c.get("/api/index").json()["entries"] == []
        assert c.get("/api/index").json()["suites"] == []
        settings["index_suite_ids"] = [ids[0], ids[0]]
        assert c.put("/api/settings", json=settings).status_code == 422


def test_default_missing_suite_still_requires_seven(session):
    ids = _suites(session)
    session.query(BenchmarkSet).filter_by(id=ids[-1]).delete()
    for sid in ids[:-1]:
        _run(session, sid, "model", 100)
    session.commit()
    with _client() as c:
        board = c.get("/api/index").json()
        assert len(board["suites"]) == 7
        assert board["suites"][-1]["missing"]
        assert board["entries"] == []


def test_index_warns_about_historical_versions_and_excludes_missing_scores(session):
    ids = _suites(session)
    for sid in ids:
        _run(session, sid, "model", None if sid == ids[-1] else 100)
    session.get(BenchmarkSet, ids[0]).version = "2.0.0"
    session.commit()
    with _client() as c:
        board = c.get("/api/index").json()
        assert board["entries"] == []
        assert any("version" in w for w in board["warnings"])
