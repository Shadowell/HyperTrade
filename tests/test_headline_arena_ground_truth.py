"""
Tests for External Ground Truth Stream & Headline Arena Integration (Issue #1).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.arc.attribution import attribution_report
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ExternalGroundTruthPolicyV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.findings import ARCReasonCode
from hypertrade.arc.ground_truth import (
    ChallengeResult,
    DirectionalPrediction,
    GroundTruthChallenge,
    HeadlineArenaClient,
    InMemoryGroundTruthClient,
)
from hypertrade.arc.observation import observe_mission
from hypertrade.arc.reflexion import ARCReflexionLedger, constraint_for_reason_code
from hypertrade.arc.store import reset_store
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app


def test_ground_truth_policy_contract() -> None:
    policy = ExternalGroundTruthPolicyV1()
    assert policy.enabled is False
    assert policy.provider == "headline_arena"
    assert policy.sync_interval_hours == 24

    goal = ARCGoalV1(objective="Test Ground Truth")
    assert goal.ground_truth.enabled is False

    goal_enabled = ARCGoalV1(
        objective="Test Ground Truth",
        ground_truth=ExternalGroundTruthPolicyV1(enabled=True, min_brier_score=Decimal("0.25")),
    )
    assert goal_enabled.ground_truth.enabled is True
    assert goal_enabled.ground_truth.min_brier_score == Decimal("0.25")

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="Trend test",
        strategy_code="class Strategy: pass",
    )
    assert attempt.ground_truth_predictions == []
    assert attempt.ground_truth_metrics == {}


def test_in_memory_ground_truth_client_lifecycle() -> None:
    client = InMemoryGroundTruthClient()
    assert client.is_configured() is True

    # Setup challenges
    now = datetime.now(UTC)
    ch1 = GroundTruthChallenge(
        challenge_id="ch_btc_01",
        asset="BTC",
        target="BTC-USDT-SWAP",
        deadline=now,
        status="open",
    )
    ch2 = GroundTruthChallenge(
        challenge_id="ch_eth_01",
        asset="ETH",
        target="ETH-USDT-SWAP",
        deadline=now,
        status="open",
    )
    client.challenges = [ch1, ch2]

    # Discovery
    btc_challenges = client.get_active_challenges("BTC")
    assert len(btc_challenges) == 1
    assert btc_challenges[0].challenge_id == "ch_btc_01"

    # Prediction submission
    pred = DirectionalPrediction(
        direction="bullish",
        confidence=0.75,
        probabilities={"bullish": 0.75, "bearish": 0.15, "neutral": 0.10},
        reasoning="Strong momentum test",
    )
    receipt = client.submit_prediction("ch_btc_01", pred, idempotency_key="test_key_1")
    assert receipt.status == "submitted"
    assert receipt.challenge_id == "ch_btc_01"
    assert receipt.direction == "bullish"
    assert receipt.confidence == 0.75
    assert len(receipt.receipt_hash) == 64

    # Settlement result
    client.results["ch_btc_01"] = ChallengeResult(
        challenge_id="ch_btc_01",
        asset="BTC",
        outcome="bullish",
        brier_score=0.0625,
        settled=True,
        settled_at=now,
        prediction_direction="bullish",
        hit=True,
    )
    res = client.get_challenge_result("ch_btc_01")
    assert res is not None
    assert res.settled is True
    assert res.hit is True


def test_headline_arena_synthesizes_prediction() -> None:
    client = HeadlineArenaClient()
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_10",
        candidate_id="cand_10",
        hypothesis="Trend breakout",
        strategy_code="class Strategy: pass",
        strategy_spec={"family": "trend_following", "tunable_parameters": {"lookback_period": 20}},
        observed_metrics={"net_return": 0.12, "sharpe": 1.6},
    )
    ch = GroundTruthChallenge(challenge_id="ch_btc", asset="BTC")
    pred = client.synthesize_prediction(attempt, ch)

    assert pred.direction == "bullish"
    assert pred.confidence >= 0.70
    assert "cand_10" in pred.reasoning
    assert pred.probabilities is not None
    assert sum(pred.probabilities.values()) == pytest.approx(1.0, abs=0.01)

    # Test bearish synthesis
    bearish_attempt = ARCCandidateAttemptV1(
        attempt_id="att_11",
        candidate_id="cand_11",
        hypothesis="Short bias",
        strategy_code="class Strategy: pass",
        strategy_spec={"family": "mean_reversion"},
        observed_metrics={"net_return": -0.08, "sharpe": 0.4},
    )
    bear_pred = client.synthesize_prediction(bearish_attempt, ch)
    assert bear_pred.direction == "bearish"


def test_ground_truth_alignment_evaluation_divergence() -> None:
    client = HeadlineArenaClient()
    # Strategy that claims high internal return (+15%)
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_div",
        candidate_id="cand_div",
        hypothesis="Curve fitted strategy",
        strategy_code="class Strategy: pass",
        observed_metrics={"net_return": 0.15},
    )

    # But 4 third-party settled challenges failed (hit rate 0%, high Brier)
    results = [
        ChallengeResult(
            challenge_id=f"ch_{i}",
            asset="BTC",
            outcome="bearish",
            prediction_direction="bullish",
            brier_score=0.45,
            settled=True,
            hit=False,
        )
        for i in range(4)
    ]

    evaluation = client.evaluate_alignment(attempt, results)
    assert evaluation.alignment == "divergent"
    assert evaluation.sample_count == 4
    assert evaluation.accuracy == 0.0
    assert evaluation.divergence_reason == ARCReasonCode.EXTERNAL_GROUND_TRUTH_DIVERGENCE.value
    assert "divergence detected" in evaluation.details.lower()


def test_ground_truth_alignment_evaluation_aligned() -> None:
    client = HeadlineArenaClient()
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_align",
        candidate_id="cand_align",
        hypothesis="Robust strategy",
        strategy_code="class Strategy: pass",
        observed_metrics={"net_return": 0.10},
    )

    # 4 settled challenges, 3 hits (75% accuracy, low Brier)
    results = [
        ChallengeResult(
            challenge_id="ch_1",
            asset="BTC",
            outcome="bullish",
            prediction_direction="bullish",
            brier_score=0.10,
            settled=True,
            hit=True,
        ),
        ChallengeResult(
            challenge_id="ch_2",
            asset="BTC",
            outcome="bullish",
            prediction_direction="bullish",
            brier_score=0.12,
            settled=True,
            hit=True,
        ),
        ChallengeResult(
            challenge_id="ch_3",
            asset="BTC",
            outcome="bullish",
            prediction_direction="bullish",
            brier_score=0.15,
            settled=True,
            hit=True,
        ),
        ChallengeResult(
            challenge_id="ch_4",
            asset="BTC",
            outcome="bearish",
            prediction_direction="bullish",
            brier_score=0.35,
            settled=True,
            hit=False,
        ),
    ]

    evaluation = client.evaluate_alignment(attempt, results)
    assert evaluation.alignment == "aligned"
    assert evaluation.accuracy == 0.75
    assert evaluation.divergence_reason is None


def test_reflexion_records_ground_truth_divergence() -> None:
    ledger = ARCReflexionLedger()
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_ref",
        candidate_id="cand_ref",
        hypothesis="Testing reflexion",
        strategy_code="class Strategy: pass",
    )

    from hypertrade.arc.ground_truth import GroundTruthEvaluation

    evaluation = GroundTruthEvaluation(
        attempt_id=attempt.attempt_id,
        alignment="divergent",
        brier_score=0.42,
        accuracy=0.25,
        sample_count=4,
        details="Third party hit rate 25%",
        divergence_reason=ARCReasonCode.EXTERNAL_GROUND_TRUTH_DIVERGENCE.value,
    )

    event = ledger.record_ground_truth_divergence(attempt, evaluation)
    assert event.failure_class == "external_ground_truth_divergence"
    assert ARCReasonCode.EXTERNAL_GROUND_TRUTH_DIVERGENCE.value in event.reason_codes
    assert "external_ground_truth" in event.failed_gates
    assert len(event.negative_constraints) > 0
    assert constraint_for_reason_code(ARCReasonCode.EXTERNAL_GROUND_TRUTH_DIVERGENCE.value) != ""


def test_attribution_report_projects_ground_truth_dimension() -> None:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    snapshot = {
        "strategy_id": 44,
        "instance_id": "paper-44",
        "strategy_version": "v1",
        "config_version": "c1",
        "external_ground_truth": {
            "brier_score": 0.18,
            "accuracy": 0.70,
            "sample_count": 10,
            "alignment": "aligned",
            "provider": "headline_arena",
        },
    }

    report = attribution_report(snapshot, now)
    assert "external_ground_truth" in report["dimensions"]
    gt_dim = report["dimensions"]["external_ground_truth"]
    assert gt_dim["state"] == "observed"
    assert gt_dim["reason"] == "external_ground_truth_recorded"
    assert gt_dim["metrics"]["brier_score"] == 0.18
    assert gt_dim["metrics"]["accuracy"] == 0.70
    assert gt_dim["metrics"]["provider"] == "headline_arena"


def test_observe_mission_syncs_ground_truth() -> None:
    reset_store()
    goal = ARCGoalV1(
        objective="Observing with Ground Truth",
        symbols=["BTC-USDT-SWAP"],
        ground_truth=ExternalGroundTruthPolicyV1(enabled=True),
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_obs",
        candidate_id="cand_obs",
        hypothesis="Obs test",
        strategy_code="class Strategy: pass",
        paper_instance_id="paper_inst_1",
    )
    ctrl = ARCController(goal=goal)
    ctrl.projection.state = "paper_observing"
    ctrl.projection.paper_started_at = datetime.now(UTC)
    ctrl.projection.attempts.append(attempt)

    mock_gt = InMemoryGroundTruthClient()
    mock_gt.challenges = [
        GroundTruthChallenge(
            challenge_id="ch_btc_live",
            asset="BTC",
            status="open",
        )
    ]

    class MockPaperClient:
        def paper_snapshot(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "status": "ok",
                "instance_id": "paper_inst_1",
                "trade_count": 5,
                "equity": 10500.0,
                "cumulative_return_pct": 5.0,
            }

        def health(self) -> dict[str, Any]:
            return {"status": "ok"}

    res = observe_mission(ctrl, client=MockPaperClient(), gt_client=mock_gt)
    assert res["status"] == "paper_observing"
    assert "ground_truth" in res
    assert res["ground_truth"]["status"] == "synced"
    assert res["ground_truth"]["new_submissions"] == 1
    assert len(attempt.ground_truth_predictions) == 1
    assert attempt.ground_truth_predictions[0]["challenge_id"] == "ch_btc_live"
    reset_store()


def test_ground_truth_api_endpoints() -> None:
    reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="arc-auth-test-secret",
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        login_resp = client.post(
            "/api/auth/login", json={"username": "admin", "password": "secret"}
        )
        assert login_resp.status_code == 200

        # 1. Challenge discovery endpoint
        resp = client.get("/api/v1/arc/ground-truth/challenges?asset=BTC")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["provider"] == "headline_arena"
        assert "challenges" in data

        # 2. Calibration endpoint
        resp_calib = client.get("/api/v1/arc/ground-truth/calibration")
        assert resp_calib.status_code == 200
        calib_data = resp_calib.json()
        assert calib_data["status"] == "ok"
        assert calib_data["provider"] == "headline_arena"
    reset_store()
