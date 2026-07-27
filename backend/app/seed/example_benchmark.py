"""Seed example benchmark demonstrating every grading mode.

This data is removable and the application does not depend on it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import BenchmarkPrompt, BenchmarkSet, PromptMessage

EXAMPLE_VERSION = "1.0.0"


def _now():
    return datetime.now(timezone.utc)


def _msg(role: str, content: str, position: int) -> PromptMessage:
    return PromptMessage(id=str(uuid.uuid4()), role=role, content=content, position=position)


def _prompt(
    *,
    benchmark_id: str,
    stable_id: str,
    title: str,
    description: str,
    category: str,
    difficulty: str,
    weight: float,
    position: int,
    grading_mode: str,
    grader_config: dict,
    messages: list[tuple[str, str]],
) -> BenchmarkPrompt:
    return BenchmarkPrompt(
        id=str(uuid.uuid4()),
        benchmark_id=benchmark_id,
        stable_id=stable_id,
        title=title,
        description=description,
        category=category,
        tags=[],
        difficulty=difficulty,
        importance_weight=weight,
        position=position,
        enabled=True,
        grading_mode=grading_mode,
        generation_overrides={},
        grader_config=grader_config,
        messages=[_msg(r, c, i) for i, (r, c) in enumerate(messages)],
    )


def build_example_benchmark() -> tuple[BenchmarkSet, list[BenchmarkPrompt]]:
    bench_id = str(uuid.uuid4())
    bench = BenchmarkSet(
        id=bench_id,
        name="LocalBench Studio Example Suite",
        description=(
            "A removable example benchmark demonstrating each grading mode: "
            "deterministic (exact, numeric, JSON, concept, multiple-choice), "
            "LLM judge, hybrid, and manual review."
        ),
        version=EXAMPLE_VERSION,
        tags=["example", "demo"],
        scoring_config={},
        performance_thresholds={
            "desired_ttft": 0.6,
            "max_ttft": 5.0,
            "desired_tps": 25.0,
            "min_tps": 3.0,
            "max_failure_rate": 0.1,
        },
        composite_weights={"quality": 0.85, "reliability": 0.10, "performance": 0.05},
        is_example=True,
    )

    prompts: list[BenchmarkPrompt] = [
        _prompt(
            benchmark_id=bench_id,
            stable_id="mc-capital",
            title="Capital of Canada (multiple choice)",
            description="Objective multiple-choice question.",
            category="knowledge",
            difficulty="easy",
            weight=1.0,
            position=0,
            grading_mode="deterministic",
            grader_config={
                "type": "multiple_choice",
                "correct_option": "C",
                "accepted_formats": ["C", "Option C", "Ottawa"],
                "points": 100.0,
            },
            messages=[("user", "What is the capital of Canada?\nA) Toronto\nB) Vancouver\nC) Ottawa\nD) Montreal\nAnswer with the letter only.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="num-area",
            title="Circle area (numeric)",
            description="Numeric answer with tolerance and a required unit.",
            category="math",
            difficulty="medium",
            weight=1.5,
            position=1,
            grading_mode="deterministic",
            grader_config={
                "type": "numeric",
                "expected_value": 314.16,
                "absolute_tolerance": 0.5,
                "relative_tolerance": 0.0,
                "required_unit": "cm²",
                "unit_aliases": ["cm2", "sq cm", "square centimeters"],
                "points": 100.0,
            },
            messages=[("user", "Compute the area of a circle with radius 10 cm. Report the numeric answer with units.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="json-user",
            title="User profile JSON (structured output)",
            description="Requires valid JSON with specific fields.",
            category="structured",
            difficulty="medium",
            weight=1.2,
            position=2,
            grading_mode="deterministic",
            grader_config={
                "type": "json",
                "require_valid_json": True,
                "required_fields": ["name", "age", "email"],
                "expected_field_values": {"age": 34},
                "allow_code_fences": True,
                "points": 100.0,
            },
            messages=[("user", "Return a JSON object describing a user named 'Ada' who is 34 years old, with fields name, age, and email. Output JSON only.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="concept-explain",
            title="Explain HTTPS (concept coverage)",
            description="Checks required and forbidden concepts.",
            category="explanation",
            difficulty="medium",
            weight=1.0,
            position=3,
            grading_mode="deterministic",
            grader_config={
                "type": "concept",
                "required_concepts": ["encryption", "TLS", "certificate"],
                "optional_concepts": ["handshake", "asymmetric"],
                "forbidden_claims": ["HTTP is secure by default"],
                "aliases": {"TLS": ["SSL", "transport layer security"]},
                "points_per_concept": 20.0,
                "cap": 100.0,
            },
            messages=[("user", "Explain in a few sentences how HTTPS keeps web traffic secure.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="judge-troubleshoot",
            title="DNS troubleshooting (LLM judge)",
            description="Open-ended troubleshooting graded by rubric.",
            category="troubleshooting",
            difficulty="hard",
            weight=2.0,
            position=4,
            grading_mode="judge",
            grader_config={
                "reference_answer": "A strong answer checks DNS resolution, distinguishes DNS failure from total connectivity loss, verifies the DHCP-supplied DNS server, and suggests using dig/nslookup and a fallback public resolver.",
                "reference_facts": [
                    "nslookup and dig test DNS directly",
                    "pinging 8.8.8.8 tests connectivity independent of DNS",
                    "DHCP provides the DNS server address",
                ],
                "required_elements": [
                    "distinguish DNS failure from connectivity failure",
                    "suggest a DNS diagnostic command",
                    "verify the configured DNS server",
                ],
                "rubric_dimensions": [
                    {"name": "correctness", "description": "Diagnosis is accurate.", "weight": 2.0, "maximum": 40},
                    {"name": "completeness", "description": "Covers required elements.", "weight": 1.5, "maximum": 25},
                    {"name": "reasoning", "description": "Logical, ordered steps.", "weight": 1.0, "maximum": 20},
                    {"name": "instruction_following", "weight": 0.5, "maximum": 10},
                    {"name": "clarity", "weight": 0.5, "maximum": 5},
                ],
                "critical_errors": ["recommends disabling all security permanently"],
                "score_caps": [],
                "judge_instructions": "Reward answers that distinguish DNS failure from total connectivity loss.",
                "strong_example": "First I'd run `nslookup example.com`; if that fails but `ping 8.8.8.8` works, the issue is DNS, not connectivity. Then I'd check the DHCP-assigned DNS server and consider a fallback like 8.8.8.8.",
                "weak_example": "Just restart your router.",
            },
            messages=[("user", "A user can reach 8.8.8.8 by IP but cannot open any website by name. Walk through how you would diagnose this, step by step.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="judge-architecture",
            title="Design a rate limiter (LLM judge)",
            description="Architecture recommendation graded by rubric.",
            category="architecture",
            difficulty="hard",
            weight=2.0,
            position=5,
            grading_mode="judge",
            grader_config={
                "reference_answer": "A good answer discusses token-bucket vs fixed-window, where state lives (in-memory vs Redis), and tradeoffs of distributed enforcement.",
                "reference_facts": [
                    "token bucket allows bursts while capping average rate",
                    "shared state is required for distributed rate limiting",
                ],
                "required_elements": [
                    "choose an algorithm with rationale",
                    "address distributed state",
                ],
                "rubric_dimensions": [
                    {"name": "correctness", "description": "Algorithm is sound.", "weight": 2.0, "maximum": 40},
                    {"name": "completeness", "description": "Covers tradeoffs.", "weight": 1.5, "maximum": 25},
                    {"name": "reasoning", "description": "Justifies choices.", "weight": 1.0, "maximum": 20},
                    {"name": "instruction_following", "weight": 0.5, "maximum": 10},
                    {"name": "clarity", "weight": 0.5, "maximum": 5},
                ],
                "critical_errors": [],
                "score_caps": [],
                "judge_instructions": "Allow either token-bucket or sliding-window as valid.",
            },
            messages=[("user", "Design a rate limiter for a public API. Describe the algorithm, where state is stored, and the main tradeoffs. Keep it under 200 words.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="hybrid-config",
            title="Safe file deletion (hybrid)",
            description="Combines a deterministic safety check with a judge rubric.",
            category="safety",
            difficulty="hard",
            weight=2.5,
            position=6,
            grading_mode="hybrid",
            grader_config={
                "deterministic_checks": [
                    {
                        "type": "regex",
                        "forbidden_patterns": [r"rm\s+-rf\s+/(?:\s|$)"],
                        "points": 100.0,
                    }
                ],
                "deterministic_weight": 40.0,
                "judge_weight": 60.0,
                "judge": {
                    "reference_answer": "A safe answer uses a specific path, warns about irreversibility, and avoids destructive wildcards.",
                    "reference_facts": ["rm -rf is irreversible", "always specify exact paths"],
                    "required_elements": ["warn about irreversibility", "avoid destructive wildcards"],
                    "rubric_dimensions": [
                        {"name": "correctness", "weight": 2.0, "maximum": 40},
                        {"name": "safety", "weight": 2.0, "maximum": 40},
                        {"name": "clarity", "weight": 1.0, "maximum": 20},
                    ],
                    "critical_errors": ["recommends rm -rf /"],
                    "score_caps": [{"applies_when": "destructive_command", "cap": 20}],
                },
                "critical_fail_caps": [{"applies_when": "destructive_command", "cap": 20}],
            },
            messages=[("user", "A user wants to remove a directory called 'old_logs' from their home folder. Give the exact command and any safety advice.")],
        ),
        _prompt(
            benchmark_id=bench_id,
            stable_id="manual-open",
            title="Open-ended creative task (manual review)",
            description="No automatic score; awaiting manual review.",
            category="writing",
            difficulty="medium",
            weight=1.0,
            position=7,
            grading_mode="manual",
            grader_config={},
            messages=[("user", "Write a two-sentence product description for a fictional smart umbrella. Be concise and creative.")],
        ),
    ]
    return bench, prompts


def seed_example_benchmark(session: Session) -> bool:
    """Insert the example benchmark if it does not already exist. Returns True if created."""
    existing = session.query(BenchmarkSet).filter(BenchmarkSet.is_example.is_(True)).first()
    if existing:
        return False
    bench, prompts = build_example_benchmark()
    session.add(bench)
    session.flush()
    for p in prompts:
        p.benchmark_id = bench.id
        session.add(p)
        session.flush()
        for m in p.messages:
            m.prompt_id = p.id
            session.add(m)
    return True
