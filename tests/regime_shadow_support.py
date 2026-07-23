from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypertrade.db import (
    Database,
    ExperimentManifest,
    PaperCohortSnapshot,
    PortfolioObservationWindow,
    StrategyCardSnapshot,
)
from hypertrade.portfolio.market_regime_v2 import MarketRegimeSnapshotServiceV2
from hypertrade.portfolio.regime_shadow_schemas import (
    MarketRegimeCaptureV2,
    MarketRegimeEvidenceV2,
    RegimeShadowBuildV2,
    ShadowAllocationPolicyV2,
)

DECISION = datetime.now(UTC) + timedelta(minutes=5)


def hash_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def seed_sources(
    db: Database,
    *,
    suffix: str = "base",
    capacities: tuple[str, str] = ("80000", "80000"),
    liquidities: tuple[str, str] = ("passed", "passed"),
    cost_bps: tuple[str, str] = ("10", "12"),
    correlation: str | None = "0.2",
    fits: tuple[list[str], list[str]] = (["trend"], ["trend"]),
) -> tuple[str, str]:
    card_ids = (f"card-{suffix}-a", f"card-{suffix}-b")
    window_id = f"pwin-{suffix}"
    members: list[dict[str, Any]] = []
    rows: list[Any] = []
    for index, card_id in enumerate(card_ids):
        manifest_id = f"expm-{suffix}-{index}"
        snapshot_id = f"scsnap-{suffix}-{index}"
        rows.append(
            ExperimentManifest(
                id=manifest_id,
                schema_version="experiment_manifest.v1",
                fingerprint=hash_value(f"manifest-{suffix}-{index}"),
                strategy_key=f"strategy-{suffix}-{index}",
                canonical_json={
                    "strategy_spec": {
                        "symbols": ["BTC-USDT"],
                        "timeframes": ["1H"],
                    },
                    "costs": {
                        "fee_bps": cost_bps[index],
                        "slippage_bps": "2",
                    },
                },
                created_by="test",
                created_at=DECISION - timedelta(hours=2),
                updated_at=DECISION - timedelta(hours=2),
            )
        )
        rows.append(
            StrategyCardSnapshot(
                id=snapshot_id,
                card_id=card_id,
                lineage_id=f"lineage-{suffix}-{index}",
                version_id=f"version-{suffix}-{index}",
                schema_version="strategy_card.v2",
                lifecycle_status="observing",
                completeness_score=Decimal("1"),
                content_hash=hash_value(f"card-{suffix}-{index}"),
                card_json={
                    "schema_version": "strategy_card.v2",
                    "paper_status": "paper_observing",
                    "capacity": capacities[index],
                    "liquidity": liquidities[index],
                    "declared_regime_fit": fits[index],
                },
                created_by="test",
                created_at=DECISION - timedelta(hours=2),
                updated_at=DECISION - timedelta(hours=2),
            )
        )
        members.append(
            {
                "card_id": card_id,
                "strategy_version_id": f"version-{suffix}-{index}",
                "comparison_key": "same-comparison-group",
                "comparable": True,
                "reasons": [],
                "dimensions": {"symbols": ["BTC-USDT"]},
                "metrics": {
                    "volatility_proxy": "0.02" if index == 0 else "0.04",
                    "max_drawdown_pct": "2",
                },
                "source_refs": {
                    "card_snapshot_id": snapshot_id,
                    "manifest_id": manifest_id,
                },
            }
        )
    pairs = (
        []
        if correlation is None
        else [
            {
                "left_card_id": card_ids[0],
                "right_card_id": card_ids[1],
                "correlation": correlation,
                "sample_count": 30,
                "status": "available",
            }
        ]
    )
    rows.append(
        PortfolioObservationWindow(
            id=window_id,
            schema_version="portfolio_observation_window.v1",
            policy_version="portfolio_evidence_policy.v1",
            status="available",
            horizon_days=30,
            bucket_minutes=1440,
            window_start=DECISION - timedelta(days=30),
            window_end=DECISION - timedelta(minutes=10),
            request_hash=hash_value(f"window-request-{suffix}"),
            source_hash=hash_value(f"window-source-{suffix}"),
            content_hash=hash_value(f"window-content-{suffix}"),
            idempotency_key=f"window-idempotency-{suffix}",
            source_refs_json={},
            quality_json={"status": "available"},
            strategy_summaries_json=[],
            pairwise_json=pairs,
            created_by="test",
            created_at=DECISION - timedelta(minutes=9),
            updated_at=DECISION - timedelta(minutes=9),
        )
    )
    cohort_id = f"pcoh-{suffix}"
    rows.append(
        PaperCohortSnapshot(
            id=cohort_id,
            cohort_key=hash_value(f"cohort-key-{suffix}"),
            version_number=1,
            schema_version="paper_cohort.v1",
            policy_version="paper_cohort_policy.v1",
            policy_hash=hash_value("cohort-policy"),
            status="review_ready",
            observation_window_id=window_id,
            intake_count=2,
            comparable_count=2,
            proposal_count=2,
            request_hash=hash_value(f"cohort-request-{suffix}"),
            source_hash=hash_value(f"cohort-source-{suffix}"),
            content_hash=hash_value(f"cohort-content-{suffix}"),
            idempotency_key=f"cohort-idempotency-{suffix}",
            snapshot_json={"members": members},
            created_by="test",
            created_at=DECISION - timedelta(minutes=8),
            updated_at=DECISION - timedelta(minutes=8),
        )
    )
    with db.session() as session:
        session.add_all(rows)
    regime = capture_regime(db, suffix=suffix)
    return cohort_id, regime["id"]


def capture_regime(
    db: Database,
    *,
    suffix: str,
    trend: str = "0.8",
    range_score: str = "0.2",
) -> dict[str, Any]:
    return MarketRegimeSnapshotServiceV2(db).capture(
        MarketRegimeCaptureV2(
            evidence=MarketRegimeEvidenceV2(
                as_of=DECISION - timedelta(minutes=7),
                available_at=DECISION - timedelta(minutes=8),
                source_refs=[f"world-state:{suffix}"],
                source_hash="sha256:" + hash_value(f"regime-{suffix}"),
                trend_score=Decimal(trend),
                range_score=Decimal(range_score),
                high_volatility_score=Decimal("0.1"),
                stress_score=Decimal("0.1"),
                liquidity_score=Decimal("0.1"),
                correlation_score=Decimal("0.1"),
            ),
            freshness_minutes=60,
            idempotency_key=f"regime-idempotency-{suffix}",
        ),
        actor="test",
        now=DECISION - timedelta(minutes=5),
    )


def policy(**updates: Any) -> ShadowAllocationPolicyV2:
    values: dict[str, Any] = {
        "templates": [
            "equal_weight",
            "inverse_volatility",
            "capped_risk_contribution",
            "constrained_risk_adjusted",
        ],
        "hypothetical_notional": Decimal("100000"),
        "min_members": 2,
        "max_members": 4,
        "max_strategy_weight": Decimal("0.70"),
        "max_symbol_weight": Decimal("1"),
        "max_pair_correlation": Decimal("0.80"),
        "max_turnover": Decimal("1"),
        "max_weight_delta": Decimal("1"),
        "max_estimated_cost_bps": Decimal("100"),
        "entry_threshold": Decimal("0.10"),
        "exit_threshold": Decimal("0.05"),
        "confirmation_windows": 1,
        "minimum_dwell_hours": 24,
        "cooldown_hours": 24,
        "valid_minutes": 60,
    }
    values.update(updates)
    return ShadowAllocationPolicyV2.model_validate(values)


def build_request(
    cohort_id: str,
    regime_id: str,
    *,
    key: str = "regime-shadow-build-001",
    previous_target_id: str = "",
    allocation_policy: ShadowAllocationPolicyV2 | None = None,
) -> RegimeShadowBuildV2:
    return RegimeShadowBuildV2(
        decision_at=DECISION,
        regime_snapshot_id=regime_id,
        cohort_snapshot_id=cohort_id,
        previous_target_id=previous_target_id,
        policy=allocation_policy or policy(),
        idempotency_key=key,
    )
