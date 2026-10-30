"""Retire the original bundled Master while keeping immutable run snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "0005_retire_master"
down_revision = "0004_retire_example"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Match bundled provenance, not similarly named user-created suites.
    rows = connection.execute(sa.text(
        "SELECT id, tags FROM benchmark_sets WHERE name = 'Master Suite'"
    )).all()
    import json

    retired = []
    for sid, tags in rows:
        tags = json.loads(tags) if isinstance(tags, str) else tags
        if "master" in (tags or []) and "cross-domain" in (tags or []):
            retired.append(sid)
            # Alembic's SQLite connection may not enable FK enforcement, so
            # explicitly clean children. Runs have independent snapshot data
            # and deliberately no FK to the mutable benchmark definition.
            connection.execute(sa.text(
                "DELETE FROM prompt_messages WHERE prompt_id IN "
                "(SELECT id FROM benchmark_prompts WHERE benchmark_id = :id)"
            ), {"id": sid})
            connection.execute(sa.text("DELETE FROM benchmark_prompts WHERE benchmark_id = :id"), {"id": sid})
            connection.execute(sa.text("DELETE FROM benchmark_sets WHERE id = :id"), {"id": sid})
    # Remove retired IDs from explicit Index choices; preserve all other choices.
    if retired:
        value = connection.execute(sa.text("SELECT value FROM application_settings WHERE key = 'app'")).scalar()
        if value:
            settings = json.loads(value) if isinstance(value, str) else value
            selected = settings.get("index_suite_ids")
            if isinstance(selected, list) and any(sid in retired for sid in selected):
                settings["index_suite_ids"] = [sid for sid in selected if sid not in retired]
                connection.execute(sa.text("UPDATE application_settings SET value = :value WHERE key = 'app'"),
                                   {"value": json.dumps(settings)})


def downgrade():
    # Retired definitions are not restored; historical run snapshots remain.
    pass
