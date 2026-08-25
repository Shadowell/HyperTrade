from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from hypertrade.db import Database, ResearchEvidence, ResearchMandate, StrategyVersion
from hypertrade.research.discovery_schemas import (
    AlphaHypothesisV1,
    DiscoveryExperimentContextV1,
    DiscoveryMandateV1,
    DiscoveryProposalV1,
    DiscoveryRequestV1,
    MarketPhenomenonV1,
    NoveltyComparisonV1,
)
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import (
    ExperimentCosts,
    ExperimentManifestV1,
    ExperimentRegister,
    ExperimentVersions,
    ExperimentWindow,
)
from hypertrade.research.schemas import StrategySpecDraft
from sqlalchemy import select

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


class FakeDiscoveryAdapter:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[str] = []
        self.created_config: dict[str, Any] = {}

    def strategy_validate_code(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_validate_code")
        return {"validation": {"valid": self.valid, "sandbox": "networkless"}}

    def strategy_create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_create")
        self.created_config = dict(kwargs["config"])
        return {"strategy": {"id": 8128, "source": "dynamic_db"}}


def _existing_manifest(mandate_id: str) -> ExperimentManifestV1:
    return ExperimentManifestV1(
        strategy_spec=StrategySpecDraft(
            mandate_id=mandate_id,
            strategy_key="existing_btc_trend",
            title="Existing BTC trend strategy",
            hypothesis="Persistent BTC price trends can survive bounded costs.",
            symbols=["BTC-USDT-SWAP"],
            timeframes=["1H"],
            strategy_category="TREND",
            entry_logic="Enter after a confirmed moving average trend breakout.",
            exit_logic="Exit after trend reversal or the risk stop triggers.",
            risk_conditions=["stop after bounded drawdown"],
            data_requirements=["versioned OHLCV"],
            parameter_bounds={"lookback": {"min": 10, "max": 100, "step": 5}},
            invalidation_conditions=["trend premium disappears after costs"],
        ),
        strategy_code_sha256="1" * 64,
        strategy_code_ref="bitpro:strategy:100",
        parameters={"lookback": Decimal("20")},
        exchange="OKX",
        market_type="SWAP",
        windows=[
            ExperimentWindow(
                name="locked_oos",
                start=datetime(2026, 5, 1, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            )
        ],
        costs=ExperimentCosts(
            maker_fee_bps=Decimal("2"),
            taker_fee_bps=Decimal("5"),
            slippage_bps=Decimal("5"),
            funding_mode="included",
        ),
        data_snapshot_hash="2" * 64,
        versions=ExperimentVersions(
            provider="openai",
            model="gpt-5",
            prompt_hash="3" * 64,
            tool_registry_hash="4" * 64,
            policy_hash="5" * 64,
            mcp_contract_version="bitpro-mcp-v1",
            git_commit_sha="abcdef1",
        ),
    )


def seeded_discovery_db() -> tuple[Database, dict[str, str]]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        mandate = ResearchMandate(
            name="Discovery fixture mandate",
            status="active",
            market_type="SWAP",
            symbols_json=["BTC-USDT-SWAP"],
            timeframes_json=["1H"],
            strategy_categories_json=["TREND", "CARRY_FUNDING"],
            budget_json={},
            validation_json={},
            paper_promotion_mode="manual_approval",
            live_mode="disabled",
            audit_json=[],
        )
        session.add(mandate)
        session.flush()
        evidence = ResearchEvidence(
            schema_version="research_evidence.v2",
            evidence_type="fact",
            status="active",
            claim="BTC funding dispersion remained elevated while price momentum was neutral.",
            symbols_json=["BTC-USDT-SWAP"],
            timeframes_json=["1H"],
            market_type="SWAP",
            scope_json={},
            sources_json=[
                {
                    "source_type": "bitpro_result",
                    "source_id": "funding-window-20260721",
                    "observed_at": NOW.isoformat(),
                    "content_hash": "sha256:" + "6" * 64,
                    "availability": "available",
                }
            ],
            confidence=Decimal("0.8"),
            as_of=NOW,
            valid_until=datetime(2026, 7, 22, 12, tzinfo=UTC),
            content_hash="7" * 64,
            payload_json={},
            lifecycle_json=[],
            created_by="test",
        )
        session.add(evidence)
        session.flush()
        refs = {"mandate_id": mandate.id, "evidence_id": evidence.id}
    registration = ExperimentLedgerService(db).register(
        ExperimentRegister(
            manifest=_existing_manifest(refs["mandate_id"]),
            idempotency_key="discovery-existing-manifest",
        ),
        actor="test",
    )
    with db.session() as session:
        version = session.scalar(
            select(StrategyVersion).where(
                StrategyVersion.manifest_id == registration["manifest"]["id"]
            )
        )
        assert version is not None
        refs["existing_version_id"] = version.id
    return db, refs


def discovery_request(
    refs: dict[str, str],
    *,
    key: str = "discovery-request-001",
    proposal_changes: dict[str, Any] | None = None,
    mandate_changes: dict[str, Any] | None = None,
) -> DiscoveryRequestV1:
    phenomenon = MarketPhenomenonV1(
        phenomenon_key="btc_funding_dispersion",
        description="BTC funding dispersion persists during a neutral price regime.",
        evidence_ids=[refs["evidence_id"]],
        symbols=["BTC-USDT-SWAP"],
        timeframes=["1H"],
        window_start=datetime(2026, 7, 20, tzinfo=UTC),
        window_end=datetime(2026, 7, 21, 11, tzinfo=UTC),
        observed_at=NOW,
        statistics={"funding_zscore": Decimal("2.4")},
        regimes=["neutral_price_high_funding"],
        alternative_explanations=["temporary leverage imbalance"],
        unknowns=["venue transfer latency"],
    )
    spec = StrategySpecDraft(
        mandate_id=refs["mandate_id"],
        strategy_key="btc_funding_reversal_new",
        title="BTC funding dispersion reversal",
        hypothesis="Extreme funding dispersion mean reverts after price momentum is neutral.",
        symbols=["BTC-USDT-SWAP"],
        timeframes=["1H"],
        strategy_category="CARRY_FUNDING",
        entry_logic="Enter against extreme funding only when price momentum remains neutral.",
        exit_logic="Exit when funding normalizes or price momentum invalidates the setup.",
        risk_conditions=["cap exposure during volatility expansion"],
        data_requirements=["versioned funding and OHLCV"],
        parameter_bounds={"funding_z": {"min": 1.5, "max": 4.0, "step": 0.25}},
        invalidation_conditions=["net carry remains adverse after normalization"],
    )
    hypothesis = AlphaHypothesisV1(
        hypothesis_key="btc_funding_reversal",
        strategy_family="carry_funding",
        phenomenon_keys=[phenomenon.phenomenon_key],
        economic_rationale=(
            "Crowded perpetual positioning pays an unsustainable premium before normalization."
        ),
        features=["funding_zscore", "neutral_price_momentum"],
        expected_regimes=["neutral_price_high_funding"],
        failure_conditions=["funding remains structurally elevated"],
        required_data=["funding", "OHLCV"],
        falsification_criteria=["locked OOS net carry is non-positive after costs"],
        distinguishing_dimensions=["funding exposure rather than directional trend"],
        strategy_spec=spec,
        frozen_at=NOW,
    )
    values: dict[str, Any] = {
        "phenomenon": phenomenon,
        "hypothesis": hypothesis,
        "experiment": DiscoveryExperimentContextV1(
            exchange="OKX",
            market_type="SWAP",
            windows=[
                ExperimentWindow(
                    name="locked_oos",
                    start=datetime(2026, 6, 1, tzinfo=UTC),
                    end=datetime(2026, 7, 1, tzinfo=UTC),
                )
            ],
            costs=ExperimentCosts(
                maker_fee_bps=Decimal("2"),
                taker_fee_bps=Decimal("5"),
                slippage_bps=Decimal("5"),
                funding_mode="included",
            ),
            data_snapshot_hash="8" * 64,
            versions=ExperimentVersions(
                provider="openai",
                model="gpt-5",
                prompt_hash="9" * 64,
                tool_registry_hash="a" * 64,
                policy_hash="b" * 64,
                mcp_contract_version="bitpro-mcp-v1",
                git_commit_sha="abcdef2",
            ),
        ),
        "strategy_code": (
            "from app.core.execution.base_strategy import BaseStrategy\n"
            "\n"
            "\n"
            "class FundingReversal(BaseStrategy):\n"
            "    async def on_bar(self, bar: BarData):\n"
            "        return None\n"
        ),
        "template_version": "discovery-template-v1",
        "novelty_comparisons": [
            NoveltyComparisonV1(
                existing_version_id=refs["existing_version_id"],
                return_correlation=Decimal("0.2"),
                signal_similarity=Decimal("0.1"),
                regime_overlap=Decimal("0.1"),
            )
        ],
        "model_calls": 1,
        "tool_calls": 0,
    }
    values.update(proposal_changes or {})
    mandate_values: dict[str, Any] = {
        "research_mandate_id": refs["mandate_id"],
        "evidence_ids": [refs["evidence_id"]],
        "symbols": ["BTC-USDT-SWAP"],
        "timeframes": ["1H"],
        "market_type": "SWAP",
        "data_sources": ["bitpro_result"],
        "strategy_families": ["trend", "carry_funding"],
        "forbidden_features": ["future_return"],
        "max_phenomena": 3,
        "max_hypotheses": 3,
        "max_candidates": 2,
        "max_model_calls": 3,
        "max_tool_calls": 6,
        "max_wall_seconds": 60,
        "freshness_hours": 24,
        "deterministic_seed": 128,
    }
    mandate_values.update(mandate_changes or {})
    return DiscoveryRequestV1(
        mandate=DiscoveryMandateV1.model_validate(mandate_values),
        proposals=[DiscoveryProposalV1.model_validate(values)],
        idempotency_key=key,
    )
