"""Builders shared by the observation exit and the observation throttle tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.arc.forward_outcomes import ForwardOutcomeLedger
from hypertrade.arc.store import save_mission
from hypertrade.db import Database

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
STARTED = NOW - timedelta(days=3)
PARENT = 41
CHALLENGER = "42"
INSTANCE = "paper_42"


def observing_mission(
    mission_id: str = "arc_obs",
    *,
    parent: int | None = PARENT,
    challenger: str | None = CHALLENGER,
    instance: str | None = INSTANCE,
    target: str = "bitpro",
    started: datetime | None = STARTED,
    review_required: bool = True,
    observation: dict[str, Any] | None = None,
    feedback: bool = False,
    state: str = "paper_observing",
) -> ARCController:
    """A persisted mission in paper_observing whose one attempt holds the Paper instance.

    `parent=None` builds a mission the evolution loop did not create (no evolution_context).
    """
    context = (
        {
            "target_id": target,
            "source_strategy_id": parent,
            "source_instance_id": "paper_parent",
            "trigger_source": "launch",
            "cycle_id": "evo_1_1",
        }
        if parent is not None
        else None
    )
    goal = ARCGoalV1(
        objective="evolve the source strategy",
        symbols=["BTC-USDT-SWAP"],
        paper_review_required=review_required,
        evolution_context=context,
    )
    if feedback:
        goal.feedback.enabled = True
    controller = ARCController(mission_id=mission_id, goal=goal)
    controller.projection.attempts = [
        ARCCandidateAttemptV1(
            attempt_id="att1",
            candidate_id="cand1",
            hypothesis="faster entry",
            strategy_code="class X: pass",
            state="paper_observing",
            bitpro_strategy_id=challenger,
            paper_instance_id=instance,
        )
    ]
    controller.projection.state = state  # type: ignore[assignment]
    controller.projection.paper_review = {
        "status": "paper_observing",
        "attempt_id": "att1",
        "paper_instance_id": instance,
    }
    controller.projection.paper_started_at = started
    if observation is not None:
        controller.projection.paper_observation = observation
    save_mission(controller)
    return controller


def finish_lane(
    db: Database,
    *,
    parent: int | str = PARENT,
    challenger: str = CHALLENGER,
    verdict: str = "won",
    target: str = "bitpro",
    metrics: dict[str, Any] | None = None,
    ended_at: datetime | None = None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Write the ledger row the race judge writes when a lane ends."""
    row = ForwardOutcomeLedger(db).record(
        target_id=target,
        parent_strategy_id=parent,
        challenger_strategy_id=challenger,
        verdict=verdict,
        metrics=metrics if metrics is not None else {"excess_return_pct": 1.5, "slot_no": 1},
        ended_at=ended_at,
        link=False,
    )
    if recorded_at is not None:
        with db.session() as session:
            stored = session.get(ArcForwardOutcome, row["id"])
            assert stored is not None
            stored.created_at = recorded_at
    return row


class FakeBitPro:
    """BitPro's read-only paper snapshot and health, counting every call."""

    def __init__(
        self,
        *,
        instance: str = INSTANCE,
        status: str = "running",
        ended_at: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.instance = instance
        self.status = status
        self.ended_at = ended_at
        self.error = error
        self.snapshot_calls = 0
        self.health_calls = 0

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        self.snapshot_calls += 1
        if self.error is not None:
            raise self.error
        return {
            "snapshot": {
                "instance_id": self.instance,
                "status": self.status,
                "trade_count": 7,
                "equity": 100.5,
                "cumulative_return_pct": 0.5,
                "max_drawdown_pct": 0.1,
                "sharpe_ratio": 0.3,
                "session": {"ended_at": self.ended_at},
            }
        }

    def health(self) -> dict[str, Any]:
        self.health_calls += 1
        return {"status": "ok", "health": {"status": "healthy"}}
