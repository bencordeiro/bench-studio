"""Load bundled JSON benchmark suites into the database at startup.

Every ``app/seed/suites/*.json`` file uses the documented localbench-benchmark
import format (see BENCHMARK_FORMAT.md). Loading is idempotent at the same version. A newer bundled version upgrades
the matching suite in place; historical runs retain their own snapshots. A
deleted bundle is re-created on startup unless seeding is disabled.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.exports.benchmark_format import build_models_from_export, parse_benchmark_export
from app.models import BenchmarkSet

log = logging.getLogger(__name__)

SUITES_DIR = Path(__file__).resolve().parent / "suites"


def _version_tuple(version: str) -> tuple[int, ...]:
    """Parse '2.0.0' into (2, 0, 0); unparseable parts sort lowest."""
    parts = []
    for chunk in str(version or "0").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def seed_bundled_suites(session: Session) -> int:
    """Insert bundled suites, upgrading any whose shipped version is newer.

    Returns the count created or upgraded. A suite already present at the same
    (or a newer) version is left completely alone, so local edits survive.
    Upgrades keep the existing BenchmarkSet id -- past runs snapshot their own
    copy of the benchmark, so historical results are unaffected either way.
    """
    if not SUITES_DIR.exists():
        return 0
    changed = 0
    for path in sorted(SUITES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Skipping bundled suite %s: %s", path.name, exc)
            continue
        export, errors = parse_benchmark_export(data)
        if export is None:
            log.warning("Invalid bundled suite %s: %s", path.name, errors)
            continue
        existing = (
            session.query(BenchmarkSet)
            .filter(BenchmarkSet.name == export.name)
            .first()
        )
        if existing is not None and _version_tuple(export.version) <= _version_tuple(existing.version):
            continue

        bench, prompts = build_models_from_export(export)
        # Bundled suites are curated to be compared — list them on leaderboards.
        bench.show_in_leaderboards = True

        if existing is None:
            session.add(bench)
            for p in prompts:
                session.add(p)  # messages cascade via the relationship
            session.flush()
            log.info("Seeded bundled suite %r (%d prompts)", export.name, len(prompts))
        else:
            old_version = existing.version
            # Re-point the rebuilt prompts at the existing set and swap them in.
            existing.prompts.clear()
            session.flush()
            for field in (
                "description", "version", "tags", "scoring_config",
                "performance_thresholds", "composite_weights",
            ):
                setattr(existing, field, getattr(bench, field))
            existing.show_in_leaderboards = True
            for p in prompts:
                p.benchmark_id = existing.id
                # Append through the relationship so the loaded collection stays
                # in sync -- session.add() alone leaves it stale until expiry.
                existing.prompts.append(p)
            session.flush()
            log.info(
                "Upgraded bundled suite %r %s -> %s (%d prompts)",
                export.name, old_version, export.version, len(prompts),
            )
        changed += 1
    return changed
