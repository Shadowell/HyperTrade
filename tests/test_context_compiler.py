from __future__ import annotations

from datetime import timedelta

import pytest
from hypertrade.runtime.adapters.context_engine import (
    DeterministicContextCompiler,
)
from hypertrade.runtime.domain.context import ContextBudgetExceeded, ContextSourceV1
from hypertrade.runtime.domain.models import utc_now
from pydantic import ValidationError


def source(
    ref: str,
    content: str,
    *,
    required: bool = False,
    tier: int = 2,
    **updates: object,
) -> ContextSourceV1:
    values: dict[str, object] = {
        "source_ref": ref,
        "kind": "evidence",
        "tier": tier,
        "required": required,
        "content": content,
    }
    values.update(updates)
    return ContextSourceV1.model_validate(values)


def compile_sources(sources: tuple[ContextSourceV1, ...], *, budget: int = 512):
    return DeterministicContextCompiler(max_source_tokens=40).compile(
        mission_id="mis_context_test",
        plan_version=1,
        step_id="inspect",
        attempt=1,
        policy_ref="mission_context.v1",
        budget_tokens=budget,
        sources=sources,
    )


def test_context_compile_is_deterministic_and_required_first() -> None:
    sources = (
        source("evidence:z", "optional z", tier=3),
        source("mission:objective", "hard objective", required=True, tier=0),
        source("evidence:a", "optional a", tier=2),
    )

    first = compile_sources(sources)
    second = compile_sources(tuple(reversed(sources)))

    assert first.manifest_hash == second.manifest_hash
    assert [row.source_ref for row in first.decisions] == [
        "mission:objective",
        "evidence:a",
        "evidence:z",
    ]
    assert first.decisions[0].reason == "required"


def test_required_context_fails_closed_when_budget_is_too_small() -> None:
    with pytest.raises(ContextBudgetExceeded, match="required context"):
        compile_sources(
            (source("mission:objective", "x" * 3_000, required=True, tier=0),),
            budget=128,
        )


def test_optional_sources_record_stale_budget_duplicate_and_compaction_reasons() -> None:
    duplicate = source("evidence:duplicate", "same payload", tier=3)
    pack = compile_sources(
        (
            source("mission:objective", "r" * 300, required=True, tier=0),
            source("evidence:long", "long " * 100, tier=1),
            source(
                "evidence:stale",
                "stale",
                fresh_until=utc_now() - timedelta(seconds=1),
            ),
            duplicate,
            source("evidence:duplicate-copy", "same payload", tier=4),
            source("evidence:budget", "b" * 4_000, tier=5),
        ),
        budget=128,
    )
    reasons = {row.source_ref: row.reason for row in pack.decisions}

    assert reasons["evidence:long"] == "compacted"
    assert reasons["evidence:stale"] == "stale"
    assert reasons["evidence:duplicate-copy"] == "duplicate"
    assert reasons["evidence:budget"] == "budget"
    assert pack.ledger.used_tokens <= 128


def test_optional_raw_series_is_dropped_and_secret_assignment_is_redacted() -> None:
    pack = compile_sources(
        (
            source(
                "mission:objective",
                "inspect api_key=real-secret safely",
                required=True,
                tier=0,
            ),
            source("evidence:raw", '{"candles":[1,2,3]}'),
        )
    )

    assert "real-secret" not in pack.decisions[0].rendered_content
    assert pack.decisions[1].reason == "unsafe_content"


def test_context_source_refuses_wrong_content_hash() -> None:
    with pytest.raises(ValidationError, match="hash mismatch"):
        source("evidence:bad", "content", content_hash="0" * 64)
