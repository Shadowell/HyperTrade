import hashlib
import json

import pytest
from hypertrade.arc.avo import _json
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.feedback import _pending_effect
from hypertrade.arc.store import reset_store, save_mission


@pytest.fixture
def blocked():
    reset_store()
    ctrl = ARCController(
        goal=ARCGoalV1(objective="audit", research_mode="avo", paper_review_required=True)
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="a", candidate_id="c", hypothesis="h", strategy_code="code", strategy_spec={}
    )
    ctrl.projection.attempts.append(attempt)
    ctrl.projection.state = "needs_operator"
    pending = {"kind": "tool", "id": "call", "name": "develop", "arguments": {"attempt_id": "a"}}
    ctrl.projection.avo = {"pending": pending, "awaiting": [pending]}
    save_mission(ctrl)
    payload = {
        "pending_sha256": hashlib.sha256(_json(pending).encode()).hexdigest(),
        "receipt": {
            "mission_id": ctrl.mission_id,
            "tool_call_id": "call",
            "attempt_id": "a",
            "code_sha256": hashlib.sha256(b"code").hexdigest(),
            "outcome": "interrupted",
            "active_jobs": [],
            "external_evidence": {"job_id": "job", "status": "interrupted"},
        },
    }
    yield ctrl, payload
    reset_store()


def test_settlement_is_one_failed_event_and_releases_pending(blocked):
    ctrl, payload = blocked
    assert _pending_effect(ctrl.projection)
    ctrl.apply_event("avo_effect_reconciled", payload)
    assert ctrl.projection.state == "failed"
    assert not _pending_effect(ctrl.projection)
    assert ctrl.projection.avo["effect_reconciliation"] == payload
    assert ctrl.projection.attempts[0].strategy_code == "code"
    assert len(ctrl.projection.events) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("mission_id", "other"),
        ("code_sha256", "x"),
        ("active_jobs", ["running"]),
        ("outcome", "success"),
        ("external_evidence", {}),
    ],
)
def test_incomplete_or_mismatched_receipt_does_not_clear_pending(blocked, field, value):
    ctrl, payload = blocked
    payload["receipt"][field] = value
    with pytest.raises(ValueError):
        ctrl.apply_event("avo_effect_reconciled", payload)
    assert _pending_effect(ctrl.projection)
    assert ctrl.projection.state == "needs_operator"


def test_stale_pending_receipt_fails_closed(blocked):
    ctrl, payload = blocked
    payload["pending_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="changed since audit"):
        ctrl.apply_event("avo_effect_reconciled", json.loads(json.dumps(payload)))
    assert _pending_effect(ctrl.projection)
