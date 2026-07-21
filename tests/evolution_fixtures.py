from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from hypertrade.db import (
    BitProStrategyEvidenceRecord,
    Database,
    StrategyOutcome,
    StrategyVersion,
)
from hypertrade.research.evolution_schemas import (
    CandidateProposalV1,
    EvolutionMandateV1,
    EvolutionRequestV1,
    ParameterRangeV1,
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

NOW = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
SOURCE_HASH = "sha256:" + "9" * 64


def parent_manifest() -> ExperimentManifestV1:
    return ExperimentManifestV1(
        strategy_spec=StrategySpecDraft(
            mandate_id="rmand_evolution",
            strategy_key="btc_trend_existing",
            title="Existing BTC trend strategy",
            hypothesis="BTC trend persistence can remain positive after bounded trading costs.",
            symbols=["BTC-USDT-SWAP"],
            timeframes=["1H"],
            strategy_category="TREND",
            entry_logic="Enter after a confirmed trend breakout with a bounded lookback filter.",
            exit_logic="Exit after a confirmed reversal or the declared risk condition triggers.",
            risk_conditions=["maximum drawdown remains below mandate limit"],
            data_requirements=["versioned BitPro net return series"],
            parameter_bounds={
                "fast": {"min": 5, "max": 15, "step": 1},
                "threshold": {"min": 0.005, "max": 0.03, "step": 0.005},
            },
            invalidation_conditions=["settled net return decay persists"],
        ),
        strategy_code_sha256="1" * 64,
        strategy_code_ref="hypertrade:strategy:btc_trend_existing",
        parameters={"fast": Decimal("10"), "threshold": Decimal("0.01")},
        exchange="OKX",
        market_type="SWAP",
        windows=[
            ExperimentWindow(
                name="settled_history",
                start=datetime(2026, 5, 1, tzinfo=UTC),
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
            prompt_hash="2" * 64,
            tool_registry_hash="3" * 64,
            policy_hash="4" * 64,
            mcp_contract_version="bitpro-mcp-v1",
            git_commit_sha="abcdef1",
        ),
    )


def seeded_evolution_db() -> tuple[Database, dict[str, object]]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    registration = ExperimentLedgerService(db).register(
        ExperimentRegister(
            manifest=parent_manifest(),
            idempotency_key="parent-experiment-register",
        ),
        actor="test",
    )
    manifest_id = str(registration["manifest"]["id"])
    with db.session() as session:
        version = session.scalar(
            select(StrategyVersion).where(StrategyVersion.manifest_id == manifest_id)
        )
        assert version is not None
        source = BitProStrategyEvidenceRecord(
            schema_version="strategy_return_series.v1",
            evidence_type="strategy_return_series",
            source_layer="paper",
            source_id="paper_evolution_fixture",
            source_hash=SOURCE_HASH,
            content_hash="sha256:" + "7" * 64,
            as_of=datetime(2026, 7, 20, tzinfo=UTC),
            summary_json={"point_count": 100, "net_return": "-0.02"},
            refs_json={"contract_version": "bitpro-mcp-v1"},
            created_by="test",
            created_at=NOW,
        )
        session.add(source)
        session.flush()
        outcome_ids: list[str] = []
        for index, (as_of, value, regime) in enumerate(
            [
                (datetime(2026, 7, 10, tzinfo=UTC), "0.08", "trend"),
                (datetime(2026, 7, 20, tzinfo=UTC), "-0.02", "trend"),
            ]
        ):
            outcome = StrategyOutcome(
                schema_version="strategy_outcome.v1",
                outcome_type="paper_window_settled",
                strategy_lineage_id=version.lineage_id,
                strategy_version_id=version.id,
                strategy_card_id="strategy_card_evolution",
                manifest_id=manifest_id,
                experiment_execution_id="",
                mission_id="mission_evolution",
                observation_window_id="window_evolution",
                corrects_id="",
                supersedes_id="",
                as_of=as_of,
                settled_at=as_of,
                content_hash=f"{index + 5}" * 64,
                idempotency_key=f"evolution-outcome-{index}",
                outcome_json={
                    "schema_version": "strategy_outcome.v1",
                    "metrics": {"net_return": value},
                    "regimes": [regime],
                    "unknowns": [],
                    "data_gaps": [],
                    "failure_class": "",
                },
                created_by="test",
            )
            session.add(outcome)
            session.flush()
            outcome_ids.append(outcome.id)
        refs: dict[str, object] = {
            "parent_version_id": version.id,
            "parent_manifest_id": manifest_id,
            "lineage_id": version.lineage_id,
            "evidence_record_id": source.id,
            "outcome_ids": outcome_ids,
        }
    return db, refs


def evolution_request(
    refs: dict[str, object],
    *,
    proposals: list[CandidateProposalV1] | None = None,
    key: str = "evolution-request-001",
    **mandate_changes: object,
) -> EvolutionRequestV1:
    mandate: dict[str, object] = {
        "parent_version_id": refs["parent_version_id"],
        "outcome_ids": refs["outcome_ids"],
        "evidence_record_ids": [refs["evidence_record_id"]],
        "data_source_hash": SOURCE_HASH,
        "symbols": ["BTC-USDT-SWAP"],
        "timeframes": ["1H"],
        "parameter_ranges": {
            "fast": ParameterRangeV1(minimum=Decimal("5"), maximum=Decimal("15")),
            "threshold": ParameterRangeV1(
                minimum=Decimal("0.005"), maximum=Decimal("0.03")
            ),
        },
        "mutable_rule_slots": ["entry", "exit", "filter", "risk"],
        "max_candidates": 3,
        "max_trials": 10,
        "max_model_calls": 5,
        "max_tool_calls": 5,
        "max_wall_seconds": 60,
        "freshness_hours": 24,
        "deterministic_seed": 17,
    }
    mandate.update(mandate_changes)
    return EvolutionRequestV1(
        mandate=EvolutionMandateV1.model_validate(mandate),
        proposals=proposals
        or [
            CandidateProposalV1(
                proposal_kind="parameter",
                parameter_changes={"fast": Decimal("8")},
                proposal_reason="Reduce lag after settled performance decay.",
            )
        ],
        idempotency_key=key,
    )
