"""Enum definitions shared across models."""
from __future__ import annotations

import enum


class GradingMode(str, enum.Enum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    HYBRID = "hybrid"
    MANUAL = "manual"


class DeterministicGraderType(str, enum.Enum):
    EXACT = "exact"
    NUMERIC = "numeric"
    REGEX = "regex"
    CONCEPT = "concept"
    JSON = "json"
    MULTIPLE_CHOICE = "multiple_choice"


class RunStatus(str, enum.Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    WARMING_UP = "warming_up"
    RUNNING_TARGET = "running_target"
    RUNNING_DETERMINISTIC = "running_deterministic"
    RUNNING_JUDGE = "running_judge"
    RUNNING_VERIFIER = "running_verifier"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


# Terminal states in which a run has scorable results. Single source of truth
# for "this run counts" checks (results recompute, leaderboards, comparisons).
COMPLETED_STATUSES: frozenset[str] = frozenset(
    {RunStatus.COMPLETED.value, RunStatus.COMPLETED_WITH_ERRORS.value}
)


class PromptStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    AWAITING_JUDGE = "awaiting_judge"
    AWAITING_MANUAL = "awaiting_manual"


class SecretStorageMethod(str, enum.Enum):
    NONE = "none"
    KEYRING = "keyring"
    ENV = "env"
    SESSION = "session"
    PLAINTEXT = "plaintext"
