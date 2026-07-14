from __future__ import annotations

import contextlib

from hypertrade.agent.task_events import TaskEventService
from hypertrade.agent.tasks import (
    TASK_TRANSITIONS,
    AgentTaskCreate,
    AgentTaskService,
    InvalidTaskTransition,
)
from hypertrade.db import Database
from hypertrade.evals.research_os import EventCursorProjection
from hypertrade.research.node_runs import TaskNodeRunService
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

_TASK_STATUSES = tuple(TASK_TRANSITIONS)


class AgentTaskStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.db = Database("sqlite:///:memory:")
        self.db.create_all()
        self.service = AgentTaskService(self.db)
        self.task = self.service.create(
            AgentTaskCreate(
                objective="property-tested bounded task",
                idempotency_key="property-task",
            )
        )
        self.status = "queued"
        self.last_sequence = self.task.last_event_sequence

    @rule(next_status=st.sampled_from(_TASK_STATUSES))
    def request_transition(self, next_status: str) -> None:
        allowed = next_status == self.status or next_status in TASK_TRANSITIONS[self.status]
        if allowed:
            self.task = self.service.transition(
                self.task.id,
                next_status,  # type: ignore[arg-type]
                actor="property-test",
                reason=f"property:{self.status}:{next_status}",
            )
            self.status = next_status
        else:
            with contextlib.suppress(InvalidTaskTransition):
                self.service.transition(
                    self.task.id,
                    next_status,  # type: ignore[arg-type]
                    actor="property-test",
                    reason="property:invalid",
                )
                raise AssertionError(f"invalid transition unexpectedly succeeded: {next_status}")

    @invariant()
    def persisted_state_and_events_are_monotonic(self) -> None:
        stored = self.service.get(self.task.id)
        events = TaskEventService(self.db).list(self.task.id)
        sequences = [event.sequence for event in events]
        assert stored.status == self.status
        assert sequences == sorted(set(sequences))
        assert stored.last_event_sequence == (sequences[-1] if sequences else 0)
        assert stored.last_event_sequence >= self.last_sequence
        self.last_sequence = stored.last_event_sequence


class TestAgentTaskStateMachine(AgentTaskStateMachine.TestCase):
    settings = settings(max_examples=20, stateful_step_count=20, deadline=None)


@given(st.lists(st.booleans(), min_size=1, max_size=8))
@settings(max_examples=30, deadline=None)
def test_node_attempt_replay_is_append_only_and_completed_node_is_reused(
    outcomes: list[bool],
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    task = AgentTaskService(db).create(
        AgentTaskCreate(
            objective="node attempt property",
            idempotency_key="node-attempt-property",
        ),
        start_immediately=True,
    )
    nodes = TaskNodeRunService(db)
    completed_attempt = 0

    for outcome in outcomes:
        started = nodes.start(
            task.id,
            node_key="market_regime",
            role_key="market_regime",
            depends_on=["data_quality"],
            input_ref={"prompt_hash": "a" * 64},
            tool_policy={"catalog_hash": "b" * 64},
        )
        if completed_attempt:
            assert started.replayed is True
            assert started.node.attempt == completed_attempt
            continue
        assert started.replayed is False
        if outcome:
            completed = nodes.complete(started.node.id, output_ref={}, usage={})
            completed_attempt = completed.attempt
        else:
            nodes.fail(started.node.id, error={"code": "injected"})

    attempts = nodes.list(task.id)
    assert [row.attempt for row in attempts] == list(range(1, len(attempts) + 1))
    if completed_attempt:
        assert sum(row.status == "completed" for row in attempts) == 1


@given(st.lists(st.integers(min_value=0, max_value=50), min_size=1, max_size=30))
@settings(max_examples=50, deadline=None)
def test_event_cursor_accepts_only_new_high_water_marks(sequences: list[int]) -> None:
    cursor = EventCursorProjection()
    accepted: list[int] = []
    high_water = 0
    for sequence in sequences:
        if sequence > high_water:
            accepted.append(sequence)
            high_water = sequence
        cursor.consume(sequence)

    assert cursor.accepted == accepted
    assert cursor.last_sequence == high_water
