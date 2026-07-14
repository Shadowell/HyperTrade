from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypertrade.research.experiment_schemas import (
    ExperimentCosts,
    ExperimentManifestV1,
    ExperimentVersions,
    ExperimentWindow,
    canonical_manifest_json,
    experiment_fingerprint,
)
from hypertrade.research.schemas import StrategySpecDraft


def manifest(*, fee: str = "10.0", data_hash: str = "a" * 64) -> ExperimentManifestV1:
    return ExperimentManifestV1(
        strategy_spec=StrategySpecDraft(
            mandate_id="rmand_test",
            strategy_key="btc_trend_v1",
            title="BTC trend candidate",
            hypothesis="BTC hourly trend persistence can survive bounded costs.",
            symbols=["btc"],
            timeframes=["1h"],
            strategy_category="trend",
            entry_logic="Enter only after a confirmed moving-average breakout.",
            exit_logic="Exit on trend reversal or the bounded risk condition.",
            risk_conditions=["maximum drawdown gate"],
            data_requirements=["hourly OHLCV"],
            parameter_bounds={"fast": {"min": 5, "max": 10, "step": 5}},
            invalidation_conditions=["locked OOS gate fails"],
        ),
        strategy_code_sha256="b" * 64,
        strategy_code_ref="hypertrade:strategy:btc_trend_v1",
        parameters={"threshold": Decimal("0.0100"), "fast": Decimal("5.0")},
        exchange="okx",
        market_type="swap",
        windows=[
            ExperimentWindow(
                name="validation",
                start=datetime(2026, 2, 1, tzinfo=UTC),
                end=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            ExperimentWindow(
                name="in_sample",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ],
        costs=ExperimentCosts(
            maker_fee_bps=Decimal(fee),
            taker_fee_bps=Decimal(fee),
            slippage_bps=Decimal("5"),
            funding_mode="included",
        ),
        data_snapshot_hash=data_hash,
        versions=ExperimentVersions(
            provider="openai",
            model="gpt-5",
            prompt_hash="c" * 64,
            tool_registry_hash="d" * 64,
            policy_hash="e" * 64,
            mcp_contract_version="bitpro-mcp-v1",
            git_commit_sha="abcdef1",
        ),
    )


def test_fingerprint_is_canonical_across_order_and_decimal_spelling() -> None:
    left = manifest()
    payload = left.model_dump(mode="python")
    payload["windows"] = list(reversed(payload["windows"]))
    payload["parameters"] = {"fast": Decimal("5.000"), "threshold": Decimal("0.01")}
    right = ExperimentManifestV1.model_validate(payload)

    assert canonical_manifest_json(left) == canonical_manifest_json(right)
    assert experiment_fingerprint(left) == experiment_fingerprint(right)
    assert '"prompt"' not in canonical_manifest_json(left)
    assert '"private_reasoning"' not in canonical_manifest_json(left)


def test_every_semantic_cost_or_data_change_changes_fingerprint() -> None:
    baseline = experiment_fingerprint(manifest())

    assert experiment_fingerprint(manifest(fee="10.1")) != baseline
    assert experiment_fingerprint(manifest(data_hash="f" * 64)) != baseline


def test_manifest_rejects_naive_timestamps() -> None:
    payload = manifest().model_dump(mode="python")
    payload["windows"][0]["start"] = datetime(2026, 1, 1)

    try:
        ExperimentManifestV1.model_validate(payload)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive experiment time must be rejected")
