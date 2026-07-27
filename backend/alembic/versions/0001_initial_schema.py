"""Initial LocalBench Studio schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-16

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # endpoint_profiles
    op.create_table(
        "endpoint_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("base_url", sa.String(length=2000), nullable=False),
        sa.Column("default_model", sa.String(length=500)),
        sa.Column("request_timeout", sa.Float),
        sa.Column("verify_tls", sa.Boolean),
        sa.Column("custom_headers", sa.JSON),
        sa.Column("extra_body_params", sa.JSON),
        sa.Column("enabled", sa.Boolean),
        sa.Column("notes", sa.Text),
        sa.Column("has_api_key", sa.Boolean),
        sa.Column("api_key_storage", sa.String(length=40)),
        sa.Column("api_key_env_var", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_endpoint_profiles_name", "endpoint_profiles", ["name"])

    # benchmark_sets
    op.create_table(
        "benchmark_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("version", sa.String(length=50)),
        sa.Column("tags", sa.JSON),
        sa.Column("scoring_config", sa.JSON),
        sa.Column("performance_thresholds", sa.JSON),
        sa.Column("composite_weights", sa.JSON),
        sa.Column("is_example", sa.Boolean),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_benchmark_sets_name", "benchmark_sets", ["name"])

    # benchmark_prompts
    op.create_table(
        "benchmark_prompts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("benchmark_id", sa.String(length=36),
                  sa.ForeignKey("benchmark_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stable_id", sa.String(length=200)),
        sa.Column("title", sa.String(length=400)),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(length=200)),
        sa.Column("tags", sa.JSON),
        sa.Column("difficulty", sa.String(length=50)),
        sa.Column("importance_weight", sa.Float),
        sa.Column("position", sa.Integer),
        sa.Column("enabled", sa.Boolean),
        sa.Column("grading_mode", sa.String(length=30)),
        sa.Column("generation_overrides", sa.JSON),
        sa.Column("grader_config", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_benchmark_prompts_benchmark", "benchmark_prompts", ["benchmark_id"])
    op.create_index("ix_benchmark_prompts_category", "benchmark_prompts", ["category"])

    # prompt_messages
    op.create_table(
        "prompt_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("prompt_id", sa.String(length=36),
                  sa.ForeignKey("benchmark_prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("position", sa.Integer),
    )

    # benchmark_runs
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=300)),
        sa.Column("notes", sa.Text),
        sa.Column("status", sa.String(length=40)),
        sa.Column("benchmark_id", sa.String(length=36), nullable=False),
        sa.Column("benchmark_snapshot", sa.JSON),
        sa.Column("target_endpoint_id", sa.String(length=36)),
        sa.Column("target_endpoint_name", sa.String(length=200)),
        sa.Column("target_model", sa.String(length=500)),
        sa.Column("target_settings", sa.JSON),
        sa.Column("judge_endpoint_id", sa.String(length=36)),
        sa.Column("judge_endpoint_name", sa.String(length=200)),
        sa.Column("judge_model", sa.String(length=500)),
        sa.Column("judge_settings", sa.JSON),
        sa.Column("judge_enabled", sa.Boolean),
        sa.Column("verifier_enabled", sa.Boolean),
        sa.Column("run_config", sa.JSON),
        sa.Column("summary", sa.JSON),
        sa.Column("error_message", sa.Text),
        sa.Column("total_prompts", sa.Integer),
        sa.Column("completed_prompts", sa.Integer),
        sa.Column("failed_prompts", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_runs_status", "benchmark_runs", ["status"])
    op.create_index("ix_runs_created", "benchmark_runs", ["created_at"])
    op.create_index("ix_runs_model", "benchmark_runs", ["target_model"])
    op.create_index("ix_runs_benchmark", "benchmark_runs", ["benchmark_id"])

    # prompt_executions
    op.create_table(
        "prompt_executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36),
                  sa.ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_snapshot_id", sa.String(length=200)),
        sa.Column("repetition", sa.Integer),
        sa.Column("position", sa.Integer),
        sa.Column("status", sa.String(length=40)),
        sa.Column("prompt_snapshot", sa.JSON),
        sa.Column("final_score", sa.Float),
        sa.Column("max_score", sa.Float),
        sa.Column("weighted", sa.Boolean),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_executions_run", "prompt_executions", ["run_id"])
    op.create_index("ix_executions_status", "prompt_executions", ["status"])
    op.create_index("ix_executions_position", "prompt_executions", ["position"])
    op.create_index("ix_executions_score", "prompt_executions", ["final_score"])

    # target_responses
    op.create_table(
        "target_responses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text),
        sa.Column("finish_reason", sa.String(length=60)),
        sa.Column("truncated", sa.Boolean),
        sa.Column("raw", sa.JSON),
    )

    # deterministic_grades
    op.create_table(
        "deterministic_grades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grader_type", sa.String(length=40)),
        sa.Column("passed", sa.Boolean),
        sa.Column("score", sa.Float),
        sa.Column("max_score", sa.Float),
        sa.Column("details", sa.JSON),
    )

    # judge_grades
    op.create_table(
        "judge_grades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("final_score", sa.Float),
        sa.Column("raw_total", sa.Float),
        sa.Column("critical_error", sa.Boolean),
        sa.Column("score_cap", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column("dimension_scores", sa.JSON),
        sa.Column("strengths", sa.JSON),
        sa.Column("deductions", sa.JSON),
        sa.Column("raw_response", sa.Text),
        sa.Column("valid", sa.Boolean),
        sa.Column("repair_attempted", sa.Boolean),
    )

    # verifier_grades
    op.create_table(
        "verifier_grades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_score", sa.Float),
        sa.Column("verified_score", sa.Float),
        sa.Column("adjusted", sa.Boolean),
        sa.Column("confidence", sa.Float),
        sa.Column("adjustment_reason", sa.Text),
        sa.Column("problems_found", sa.JSON),
        sa.Column("raw_response", sa.Text),
        sa.Column("valid", sa.Boolean),
    )

    # manual_grades
    op.create_table(
        "manual_grades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("notes", sa.Text),
        sa.Column("dimension_scores", sa.JSON),
        sa.Column("graded_at", sa.DateTime(timezone=True)),
    )

    # performance_metrics
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36),
                  sa.ForeignKey("prompt_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_start", sa.String(length=40)),
        sa.Column("time_to_first_token", sa.Float),
        sa.Column("total_response_time", sa.Float),
        sa.Column("prompt_tokens", sa.Integer),
        sa.Column("completion_tokens", sa.Integer),
        sa.Column("total_tokens", sa.Integer),
        sa.Column("tokens_estimated", sa.Boolean),
        sa.Column("output_tokens_per_second", sa.Float),
        sa.Column("finish_reason", sa.String(length=60)),
        sa.Column("http_status", sa.Integer),
        sa.Column("retry_count", sa.Integer),
        sa.Column("truncated", sa.Boolean),
        sa.Column("response_char_count", sa.Integer),
    )

    # application_settings
    op.create_table(
        "application_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.JSON),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    for table in [
        "application_settings",
        "performance_metrics",
        "manual_grades",
        "verifier_grades",
        "judge_grades",
        "deterministic_grades",
        "target_responses",
        "prompt_executions",
        "benchmark_runs",
        "prompt_messages",
        "benchmark_prompts",
        "benchmark_sets",
        "endpoint_profiles",
    ]:
        op.drop_table(table)
