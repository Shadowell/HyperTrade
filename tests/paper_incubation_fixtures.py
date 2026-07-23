from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypertrade.db import ExperimentManifest
from hypertrade.research.paper_incubation_schemas import (
    PaperMandateCreateV1,
    PaperResearchMandateV1,
)
from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
from hypertrade.runtime.adapters.effect_store import InMemoryEffectGovernanceStore
from hypertrade.runtime.application.effect_governance import EffectGovernanceService
from validation_v2_fixtures import seeded_validation_candidate, validation_request


class FakePaperIncubationAdapter:
    def __init__(self, *, timeout_action: str = "") -> None:
        self.timeout_action = timeout_action
        self.calls: list[str] = []
        self.status = "stopped"
        self.max_drawdown_pct = "2"
        self.health_status = "healthy"

    def _maybe_timeout(self, action: str) -> None:
        self.calls.append(action)
        if self.timeout_action == action:
            self.timeout_action = ""
            raise TimeoutError(f"{action} timed out")

    def paper_configure(self, **_: Any) -> dict[str, Any]:
        self._maybe_timeout("configure")
        self.status = "configured"
        return {
            "paper": {"instance_id": "paper-instance-101", "status": self.status},
            "tool_calls": [{"tool": "paper_configure", "status": "success"}],
        }

    def paper_start(self, **_: Any) -> dict[str, Any]:
        self._maybe_timeout("start")
        self.status = "running"
        return {
            "paper": {"instance_id": "paper-instance-101", "status": self.status},
            "tool_calls": [{"tool": "paper_start", "status": "success"}],
        }

    def paper_pause(self, **_: Any) -> dict[str, Any]:
        self._maybe_timeout("pause")
        self.status = "paused"
        return {"paper": {"instance_id": "paper-instance-101", "status": self.status}}

    def paper_stop(self, **_: Any) -> dict[str, Any]:
        self._maybe_timeout("retire")
        self.status = "stopped"
        return {"paper": {"instance_id": "paper-instance-101", "status": self.status}}

    def paper_snapshot(self, **_: Any) -> dict[str, Any]:
        self.calls.append("snapshot")
        return {
            "snapshot": {
                "instance_id": "paper-instance-101",
                "status": self.status,
                "generated_at": datetime.now(UTC).isoformat(),
                "strategy_version": "sha256:strategy",
                "config_version": "sha256:config",
                "max_drawdown_pct": self.max_drawdown_pct,
                "error_count": 0,
                "data_coverage": {"equity_sample_count": 40},
            }
        }

    def paper_equity_curve(self, **_: Any) -> dict[str, Any]:
        self.calls.append("equity_curve")
        now = datetime.now(UTC)
        return {
            "equity_curve": [
                {
                    "timestamp": (now - timedelta(hours=39 - index)).isoformat(),
                    "equity": str(100 + index),
                }
                for index in range(40)
            ]
        }

    def health(self) -> dict[str, Any]:
        self.calls.append("health")
        return {"status": self.health_status}


def seeded_paper_incubation(*, validation_status: str = "validated"):
    db, refs = seeded_validation_candidate("discovery")
    changes = (
        {"regime_label_mode": "ex_post_research"} if validation_status == "needs_review" else {}
    )
    validation = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            key=f"paper-incubation-validation-{validation_status}",
            evidence_changes=changes,
        ),
        actor="test",
    )
    with db.session() as session:
        manifest = session.get(ExperimentManifest, refs["manifest_id"])
        assert manifest is not None
        refs["symbol"] = str(manifest.canonical_json["strategy_spec"]["symbols"][0])
    adapter = FakePaperIncubationAdapter()
    effects = EffectGovernanceService(
        InMemoryEffectGovernanceStore(),
        enabled_write_environments=frozenset({"paper"}),
    )
    return db, refs, validation, adapter, effects


def mandate_request(
    refs: dict[str, str],
    validation: dict[str, Any],
    *,
    key: str = "paper-research-mandate-001",
    updates: dict[str, Any] | None = None,
) -> PaperMandateCreateV1:
    now = datetime.now(UTC)
    body: dict[str, Any] = {
        "name": "Bounded Paper incubation fixture",
        "candidate_ids": [refs["candidate_id"]],
        "validation_ids": [validation["id"]],
        "validation_fingerprints": {
            refs["candidate_id"]: validation["fingerprint"],
        },
        "symbols": [refs["symbol"]],
        "paper_capital": "100",
        "max_instances": 1,
        "observation_days": [30, 60, 90],
        "allowed_actions": ["configure", "start", "observe", "pause", "retire"],
        "max_drawdown_pct": "10",
        "max_error_count": 0,
        "minimum_equity_samples": 30,
        "maker_fee_bps": "2",
        "taker_fee_bps": "5",
        "slippage_bps": "5",
        "valid_from": now - timedelta(minutes=1),
        "valid_until": now + timedelta(days=30),
        "approved_by": "human-operator",
        "revoke_mode": "safe_pause",
    }
    body.update(updates or {})
    return PaperMandateCreateV1(
        mandate=PaperResearchMandateV1.model_validate(body),
        idempotency_key=key,
    )
