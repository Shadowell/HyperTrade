"""Completed loser ablations projected into citable research memory entries."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from hypertrade.arc.ablation import ablation_memory
from hypertrade.arc.evolution_models import ArcAblationRun
from hypertrade.db import Database

DEV_END = date(2026, 8, 20)

ENTRY_KEYS = {
    "memory_id",
    "type",
    "evidence_status",
    "ablation_id",
    "outcome_id",
    "verdict",
    "parent_strategy_id",
    "challenger_strategy_id",
    "window",
    "capital",
    "baseline",
    "effects",
    "harmful",
    "helpful",
    "scope",
    "causal_claim_verified",
    "rule",
}
EFFECT_KEYS = {
    "label",
    "class",
    "delta_net_return",
    "delta_max_drawdown",
    "delta_trade_count",
    "backtest_id",
    "reason",
}
BASELINE_KEYS = {"backtest_id", "net_return", "max_drawdown", "trade_count"}


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    yield database


def _result(
    outcome_id: str,
    *,
    window: tuple[str, str] = ("2026-04-21", "2026-08-20"),
    harmful_label: str = "fast=12",
    helpful_label: str = "slow=40",
) -> dict[str, Any]:
    return {
        "schema_version": "ablation_result.v1",
        "outcome_id": outcome_id,
        "verdict": "lost_futility",
        "parent_strategy_id": "443",
        "challenger_strategy_id": "9103",
        "window": list(window),
        "capital": "10000",
        "baseline": {
            "backtest_id": 11,
            "net_return": 0.1,
            "max_drawdown": 0.05,
            "trade_count": 42,
        },
        "effects": [
            {
                "step_key": "param:fast",
                "change": {"kind": "parameter", "key": "fast", "value": 12},
                "label": harmful_label,
                "status": "completed",
                "backtest_id": 12,
                "reason": "",
                "delta_net_return": -0.02,
                "delta_max_drawdown": 0.01,
                "delta_trade_count": 3.0,
                "class": "harmful",
            },
            {
                "step_key": "param:slow",
                "change": {"kind": "parameter", "key": "slow", "value": 40},
                "label": helpful_label,
                "status": "completed",
                "backtest_id": 13,
                "reason": "",
                "delta_net_return": 0.03,
                "delta_max_drawdown": -0.005,
                "delta_trade_count": -2.0,
                "class": "helpful",
            },
        ],
        "harmful": [harmful_label],
        "helpful": [helpful_label],
        "neutral": [],
        "unknown": [],
        "incomparable": [],
        "scope": "development_window_single_factor",
        "note": "dev-only single-factor observation",
        "causal_claim_verified": False,
    }


def _run(
    db: Database,
    *,
    run_id: str,
    outcome_id: str | None = None,
    target_id: str = "bitpro",
    status: str = "completed",
    result: dict[str, Any] | None = None,
) -> None:
    with db.session() as session:
        session.add(
            ArcAblationRun(
                id=run_id,
                outcome_id=outcome_id or f"out_{run_id}",
                target_id=target_id,
                parent_strategy_id="443",
                challenger_strategy_id=run_id,
                status=status,
                result_json=result if result is not None else {},
            )
        )


def test_completed_ablations_follow_outcome_order_with_citable_memory_ids(
    db: Database,
) -> None:
    for name in ("a", "b", "c"):
        _run(
            db,
            run_id=f"run_{name}",
            outcome_id=f"out_{name}",
            result=_result(f"out_{name}"),
        )

    entries, manifest = ablation_memory(
        db,
        target_id="bitpro",
        outcome_ids=["out_c", "out_a", "out_b"],
        development_end=DEV_END,
    )

    assert [entry["outcome_id"] for entry in entries] == ["out_c", "out_a", "out_b"]
    assert [entry["memory_id"] for entry in entries] == [
        "ablation:run_c",
        "ablation:run_a",
        "ablation:run_b",
    ]
    for entry in entries:
        assert entry["type"] == "ablation"
        assert entry["causal_claim_verified"] is False
        assert set(entry) == ENTRY_KEYS
        assert not any(
            marker in key
            for key in entry
            for marker in ("metrics", "plan_json", "window_json", "final")
        )
        assert set(entry["baseline"]) == BASELINE_KEYS
        assert [effect["class"] for effect in entry["effects"]] == ["harmful", "helpful"]
        for effect in entry["effects"]:
            assert set(effect) == EFFECT_KEYS
    assert entries[0]["harmful"] == ["fast=12"]
    assert entries[0]["helpful"] == ["slow=40"]
    assert manifest == {"policy": "ablation_memory_v1", "selected": 3, "excluded": {}}


def test_unfinished_malformed_and_late_window_runs_are_excluded_with_reasons(
    db: Database,
) -> None:
    for status in ("running", "failed", "skipped"):
        _run(db, run_id=f"run_{status}", outcome_id=f"out_{status}", status=status)
    _run(db, run_id="run_malformed", outcome_id="out_malformed", result={})
    _run(
        db,
        run_id="run_late",
        outcome_id="out_late",
        result=_result("out_late", window=("2026-04-21", "2026-08-21")),
    )

    entries, manifest = ablation_memory(
        db,
        target_id="bitpro",
        outcome_ids=[
            "out_running",
            "out_failed",
            "out_skipped",
            "out_malformed",
            "out_late",
        ],
        development_end=DEV_END,
    )

    assert entries == []
    assert manifest == {
        "policy": "ablation_memory_v1",
        "selected": 0,
        "excluded": {
            "not_completed": 3,
            "malformed_result": 1,
            "outside_development_horizon": 1,
        },
    }


def test_limit_and_dedup(db: Database) -> None:
    for index in range(5):
        outcome_id = f"out_{index}"
        _run(
            db,
            run_id=f"run_{index}",
            outcome_id=outcome_id,
            result=_result(outcome_id),
        )

    entries, manifest = ablation_memory(
        db,
        target_id="bitpro",
        outcome_ids=["out_0", "out_1", "out_1", "out_2", "out_3", "out_4"],
        development_end=DEV_END,
        limit=4,
    )

    assert [entry["outcome_id"] for entry in entries] == [
        "out_0",
        "out_1",
        "out_2",
        "out_3",
    ]
    assert len({entry["memory_id"] for entry in entries}) == 4
    assert manifest == {
        "policy": "ablation_memory_v1",
        "selected": 4,
        "excluded": {"context_budget": 1},
    }


def test_other_target_and_empty_input(db: Database) -> None:
    _run(db, run_id="run_bitpro", outcome_id="out_bitpro", result=_result("out_bitpro"))
    _run(
        db,
        run_id="run_quantlab",
        outcome_id="out_quantlab",
        target_id="quantlab",
        result=_result("out_quantlab"),
    )

    entries, manifest = ablation_memory(
        db,
        target_id="bitpro",
        outcome_ids=["out_quantlab", "out_bitpro"],
        development_end=DEV_END,
    )
    assert [entry["outcome_id"] for entry in entries] == ["out_bitpro"]
    assert manifest["selected"] == 1

    assert ablation_memory(
        db, target_id="bitpro", outcome_ids=[], development_end=DEV_END
    ) == (
        [],
        {"policy": "ablation_memory_v1", "selected": 0, "excluded": {}},
    )


def test_oversized_entry_is_excluded(db: Database) -> None:
    _run(
        db,
        run_id="run_huge",
        outcome_id="out_huge",
        result=_result("out_huge", harmful_label="fast=12 " + "x" * 5000),
    )

    entries, manifest = ablation_memory(
        db,
        target_id="bitpro",
        outcome_ids=["out_huge"],
        development_end=DEV_END,
    )

    assert entries == []
    assert manifest["excluded"] == {"entry_too_large": 1}
