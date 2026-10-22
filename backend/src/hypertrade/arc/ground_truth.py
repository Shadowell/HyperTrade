"""
External Ground Truth Stream & Headline Arena Integration for ARC Paper Incubation.

Provides an objective, external, third-party forward-only evaluation stream
(Headline Arena) to apply out-of-sample selection pressure to ARC candidate
strategies during simulated paper trading, unpolluted by internal backtest data.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.findings import ARCReasonCode

logger = logging.getLogger(__name__)

DEFAULT_HEADLINE_ARENA_ORIGIN = "https://headlinearena.com"
DEFAULT_HEADLINE_ARENA_API_URL = "https://headlinearena.com/api/v1"


class GroundTruthChallenge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    challenge_id: str
    asset: str
    target: str = ""
    deadline: datetime | None = None
    resolve_at: datetime | None = None
    status: str = "open"
    dead_zone_pct: float | None = None
    resolution_criteria: str | None = None
    track: str = "financial"


class DirectionalPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    probabilities: dict[str, float] | None = None
    reasoning: str = ""
    summary: str = ""


class PredictionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str
    agent_id: str
    direction: str
    confidence: float
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    receipt_hash: str
    status: str = "submitted"
    raw_response: dict[str, Any] = Field(default_factory=dict)


class ChallengeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    challenge_id: str
    asset: str
    outcome: str | None = None
    brier_score: float | None = None
    settled: bool = False
    settled_at: datetime | None = None
    actual_price_change_pct: float | None = None
    prediction_direction: str | None = None
    hit: bool | None = None


class AgentCalibration(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str
    total_predictions: int = 0
    resolved_predictions: int = 0
    brier_score: float | None = None
    accuracy: float | None = None
    calibration_curve: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GroundTruthEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    alignment: Literal["aligned", "divergent", "indeterminate", "unsupported"] = "indeterminate"
    brier_score: float | None = None
    accuracy: float | None = None
    sample_count: int = 0
    details: str = ""
    divergence_reason: str | None = None


class ExternalGroundTruthPort(Protocol):
    """Protocol for external ground truth providers (e.g. Headline Arena)."""

    def is_configured(self) -> bool: ...

    def get_active_challenges(self, asset: str | None = None) -> list[GroundTruthChallenge]: ...

    def submit_prediction(
        self,
        challenge_id: str,
        prediction: DirectionalPrediction,
        idempotency_key: str = "",
    ) -> PredictionReceipt: ...

    def get_challenge_result(self, challenge_id: str) -> ChallengeResult | None: ...

    def get_agent_calibration(self) -> AgentCalibration | None: ...

    def synthesize_prediction(
        self,
        attempt: ARCCandidateAttemptV1,
        challenge: GroundTruthChallenge,
    ) -> DirectionalPrediction: ...

    def evaluate_alignment(
        self,
        attempt: ARCCandidateAttemptV1,
        results: list[ChallengeResult],
    ) -> GroundTruthEvaluation: ...


class HeadlineArenaClient:
    """Client for Headline Arena REST API."""

    def __init__(
        self,
        api_url: str | None = None,
        agent_id: str | None = None,
        client_secret: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.api_url = (
            api_url or os.environ.get("HEADLINE_ARENA_API_URL") or DEFAULT_HEADLINE_ARENA_API_URL
        ).rstrip("/")
        self.agent_id = agent_id or os.environ.get("HEADLINE_ARENA_AGENT_ID")
        self.client_secret = client_secret or os.environ.get("HEADLINE_ARENA_CLIENT_SECRET")
        self.api_key = api_key or os.environ.get("HEADLINE_ARENA_API_KEY")
        self.timeout_seconds = timeout_seconds
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0

    def is_configured(self) -> bool:
        """True if credentials or API key are provided."""
        return bool(self.api_key or (self.agent_id and self.client_secret))

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HyperTrade-ARC/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif self.agent_id:
            token = self._ensure_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            headers["X-Agent-Id"] = self.agent_id
        return headers

    def _ensure_token(self) -> str | None:
        now = datetime.now(UTC).timestamp()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        if not (self.agent_id and self.client_secret):
            return None

        url = f"{self.api_url}/agent/auth/token"
        payload = json.dumps(
            {"agent_id": self.agent_id, "client_secret": self.client_secret}
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "HyperTrade-ARC/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                token = data.get("access_token") or data.get("token")
                expires_in = float(data.get("expires_in") or 3600)
                if token:
                    self._cached_token = str(token)
                    self._token_expires_at = now + max(60.0, expires_in - 120.0)
                    return self._cached_token
        except Exception as exc:
            logger.warning("Headline Arena token auth failed: %s", exc)
            return None
        return None

    def get_active_challenges(self, asset: str | None = None) -> list[GroundTruthChallenge]:
        """Fetch active financial forecasting challenges from Headline Arena."""
        query_params = "?track=financial"
        if asset:
            query_params += f"&asset={urllib.parse.quote(asset)}"
        url = f"{self.api_url}/eval/challenges/active{query_params}"

        headers = self._get_headers()
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            # Fallback to public challenge endpoint if /eval/challenges/active requires auth
            alt_url = f"{self.api_url}/challenges{query_params}"
            try:
                alt_req = urllib.request.Request(alt_url, headers=headers, method="GET")
                with urllib.request.urlopen(alt_req, timeout=self.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as alt_exc:
                logger.warning(
                    "Failed to fetch Headline Arena challenges: %s (alt: %s)", exc, alt_exc
                )
                return []

        challenges_raw = data.get("challenges", data if isinstance(data, list) else [])
        results: list[GroundTruthChallenge] = []
        for item in challenges_raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("challenge_id") or item.get("id") or "")
            if not cid:
                continue
            item_asset = str(item.get("asset") or item.get("symbol") or "")
            deadline_str = item.get("deadline") or item.get("lock_at")
            resolve_str = item.get("resolve_at") or item.get("settle_at")

            deadline = None
            if deadline_str:
                with contextlib.suppress(ValueError):
                    deadline = datetime.fromisoformat(str(deadline_str).replace("Z", "+00:00"))

            resolve_at = None
            if resolve_str:
                with contextlib.suppress(ValueError):
                    resolve_at = datetime.fromisoformat(str(resolve_str).replace("Z", "+00:00"))

            results.append(
                GroundTruthChallenge(
                    challenge_id=cid,
                    asset=item_asset,
                    target=str(item.get("target") or item_asset),
                    deadline=deadline,
                    resolve_at=resolve_at,
                    status=str(item.get("status") or "open"),
                    dead_zone_pct=float(item["dead_zone_pct"])
                    if item.get("dead_zone_pct") is not None
                    else None,
                    resolution_criteria=item.get("resolution_criteria"),
                    track=str(item.get("track") or "financial"),
                )
            )
        return results

    def submit_prediction(
        self,
        challenge_id: str,
        prediction: DirectionalPrediction,
        idempotency_key: str = "",
    ) -> PredictionReceipt:
        """Submit a directional prediction to Headline Arena."""
        url = f"{self.api_url}/eval/challenges/{challenge_id}/predict"
        body: dict[str, Any] = {
            "direction": prediction.direction,
            "confidence": prediction.confidence,
            "reasoning": prediction.reasoning,
        }
        if prediction.probabilities:
            body["probabilities"] = prediction.probabilities
        if prediction.summary:
            body["summary"] = prediction.summary

        headers = self._get_headers()
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = json.dumps(body, sort_keys=True).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        submitted_at = datetime.now(UTC)
        receipt_content = (
            f"{challenge_id}:{self.agent_id}:{prediction.direction}:"
            f"{prediction.confidence}:{idempotency_key}"
        )
        receipt_hash = hashlib.sha256(receipt_content.encode("utf-8")).hexdigest()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Headline Arena prediction submission failed: %s", exc)
            return PredictionReceipt(
                challenge_id=challenge_id,
                agent_id=self.agent_id or "unauthenticated_agent",
                direction=prediction.direction,
                confidence=prediction.confidence,
                submitted_at=submitted_at,
                receipt_hash=receipt_hash,
                status="failed",
                raw_response={"error": str(exc)},
            )

        return PredictionReceipt(
            challenge_id=challenge_id,
            agent_id=str(resp_data.get("agent_id") or self.agent_id or "registered_agent"),
            direction=prediction.direction,
            confidence=prediction.confidence,
            submitted_at=submitted_at,
            receipt_hash=receipt_hash,
            status="submitted",
            raw_response=resp_data,
        )

    def get_challenge_result(self, challenge_id: str) -> ChallengeResult | None:
        """Fetch settlement result and Brier score for a challenge."""
        url = f"{self.api_url}/eval/challenges/{challenge_id}/result"
        headers = self._get_headers()
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning(
                "Failed to fetch Headline Arena challenge result for %s: %s", challenge_id, exc
            )
            return None

        outcome = data.get("outcome") or data.get("settled_outcome")
        brier = data.get("brier_score")
        return ChallengeResult(
            challenge_id=challenge_id,
            asset=str(data.get("asset") or ""),
            outcome=str(outcome) if outcome else None,
            brier_score=float(brier) if brier is not None else None,
            settled=bool(data.get("settled", outcome is not None)),
            actual_price_change_pct=float(data["price_change_pct"])
            if data.get("price_change_pct") is not None
            else None,
            prediction_direction=data.get("prediction_direction"),
            hit=data.get("hit"),
        )

    def get_agent_calibration(self) -> AgentCalibration | None:
        """Fetch agent calibration curve and aggregate performance metrics."""
        endpoint = (
            f"{self.api_url}/eval/agents/{self.agent_id}/calibration"
            if self.agent_id
            else f"{self.api_url}/eval/calibration"
        )
        headers = self._get_headers()
        req = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Failed to fetch Headline Arena calibration: %s", exc)
            return None

        curve = data.get("calibration_curve") or data.get("bins") or []
        return AgentCalibration(
            agent_id=str(data.get("agent_id") or self.agent_id or "global"),
            total_predictions=int(data.get("total_predictions") or data.get("count") or 0),
            resolved_predictions=int(data.get("resolved_predictions") or 0),
            brier_score=float(data["brier_score"]) if data.get("brier_score") is not None else None,
            accuracy=float(data["accuracy"]) if data.get("accuracy") is not None else None,
            calibration_curve=curve if isinstance(curve, list) else [],
        )

    def synthesize_prediction(
        self,
        attempt: ARCCandidateAttemptV1,
        challenge: GroundTruthChallenge,
    ) -> DirectionalPrediction:
        """Extract or synthesize an objective directional forecast from candidate strategy logic."""
        spec = attempt.strategy_spec
        family = str(spec.get("family") or "trend_following")
        params = spec.get("tunable_parameters") or {}
        metrics = attempt.observed_metrics

        direction: Literal["bullish", "bearish", "neutral"] = "bullish"
        confidence: float = 0.65

        net_return = metrics.get("net_return") or metrics.get("is_net_return")
        sharpe = metrics.get("sharpe") or metrics.get("is_sharpe")

        if net_return is not None:
            try:
                ret_val = float(net_return)
                if ret_val < -0.02:
                    direction = "bearish"
                elif abs(ret_val) <= 0.02:
                    direction = "neutral"
                else:
                    direction = "bullish"
            except (ValueError, TypeError):
                direction = "bullish"

        if sharpe is not None:
            try:
                sharpe_val = float(sharpe)
                if sharpe_val > 1.8:
                    confidence = 0.80
                elif sharpe_val > 1.2:
                    confidence = 0.70
                elif sharpe_val < 0.5:
                    confidence = 0.52
                else:
                    confidence = 0.60
            except (ValueError, TypeError):
                confidence = 0.60

        probs: dict[str, float]
        if direction == "bullish":
            probs = {
                "bullish": confidence,
                "bearish": round((1.0 - confidence) * 0.6, 3),
                "neutral": round((1.0 - confidence) * 0.4, 3),
            }
        elif direction == "bearish":
            probs = {
                "bearish": confidence,
                "bullish": round((1.0 - confidence) * 0.6, 3),
                "neutral": round((1.0 - confidence) * 0.4, 3),
            }
        else:
            probs = {
                "neutral": confidence,
                "bullish": round((1.0 - confidence) / 2.0, 3),
                "bearish": round((1.0 - confidence) / 2.0, 3),
            }

        total_p = sum(probs.values())
        if total_p > 0:
            probs = {k: round(v / total_p, 4) for k, v in probs.items()}

        reasoning = (
            f"ARC Candidate {attempt.candidate_id} ({family}): "
            f"Tunable parameters={params}. "
            f"Observed Sharpe={sharpe or 'N/A'}, net return={net_return or 'N/A'}. "
            f"Directional forecast {direction} derived for {challenge.asset} "
            f"with confidence {confidence:.2f}."
        )

        return DirectionalPrediction(
            direction=direction,
            confidence=confidence,
            probabilities=probs,
            reasoning=reasoning,
            summary=f"ARC {attempt.candidate_id} {direction.upper()} ({confidence:.0%})",
        )

    def evaluate_alignment(
        self,
        attempt: ARCCandidateAttemptV1,
        results: list[ChallengeResult],
    ) -> GroundTruthEvaluation:
        """Evaluate alignment between simulated strategy performance and third-party truth."""
        settled = [
            r
            for r in results
            if r.settled and r.outcome is not None and r.prediction_direction is not None
        ]
        if not settled:
            return GroundTruthEvaluation(
                attempt_id=attempt.attempt_id,
                alignment="indeterminate",
                details="No settled external ground truth challenges available yet",
            )

        hits = sum(1 for r in settled if r.outcome == r.prediction_direction)
        accuracy = hits / len(settled)

        brier_scores = [r.brier_score for r in settled if r.brier_score is not None]
        avg_brier = sum(brier_scores) / len(brier_scores) if brier_scores else None

        paper_return = None
        for key in ("net_return", "cumulative_return_pct", "pnl"):
            if key in attempt.observed_metrics:
                try:
                    paper_return = float(attempt.observed_metrics[key])
                    break
                except (ValueError, TypeError):
                    continue

        if (
            len(settled) >= 3
            and paper_return is not None
            and paper_return > 0.05
            and (accuracy < 0.40 or (avg_brier and avg_brier > 0.35))
        ):
            divergence_details = (
                f"External Ground Truth divergence detected: strategy paper return "
                f"is {paper_return:.1%}, but external forward hit rate is only "
                f"{accuracy:.1%} (Brier: {avg_brier or 'N/A'}) "
                f"over {len(settled)} settled challenges."
            )
            return GroundTruthEvaluation(
                attempt_id=attempt.attempt_id,
                alignment="divergent",
                brier_score=avg_brier,
                accuracy=accuracy,
                sample_count=len(settled),
                details=divergence_details,
                divergence_reason=ARCReasonCode.EXTERNAL_GROUND_TRUTH_DIVERGENCE.value,
            )

        if len(settled) >= 3 and (accuracy >= 0.55 or (avg_brier and avg_brier <= 0.22)):
            aligned_details = (
                f"External Ground Truth validated: forward hit rate is {accuracy:.1%}, "
                f"Brier score is {avg_brier or 'N/A'} over {len(settled)} settled challenges."
            )
            return GroundTruthEvaluation(
                attempt_id=attempt.attempt_id,
                alignment="aligned",
                brier_score=avg_brier,
                accuracy=accuracy,
                sample_count=len(settled),
                details=aligned_details,
            )

        indet_details = (
            f"{len(settled)} challenges settled (accuracy={accuracy:.1%}, "
            f"brier={avg_brier or 'N/A'}), continuing observation."
        )
        return GroundTruthEvaluation(
            attempt_id=attempt.attempt_id,
            alignment="indeterminate",
            brier_score=avg_brier,
            accuracy=accuracy,
            sample_count=len(settled),
            details=indet_details,
        )


class InMemoryGroundTruthClient:
    """In-memory test fixture client for deterministic offline testing."""

    def __init__(self) -> None:
        self.challenges: list[GroundTruthChallenge] = []
        self.predictions: dict[str, list[PredictionReceipt]] = {}
        self.results: dict[str, ChallengeResult] = {}
        self.calibration: AgentCalibration | None = None
        self._configured: bool = True

    def is_configured(self) -> bool:
        return self._configured

    def get_active_challenges(self, asset: str | None = None) -> list[GroundTruthChallenge]:
        if asset:
            return [
                c
                for c in self.challenges
                if c.asset.upper() == asset.upper() and c.status == "open"
            ]
        return [c for c in self.challenges if c.status == "open"]

    def submit_prediction(
        self,
        challenge_id: str,
        prediction: DirectionalPrediction,
        idempotency_key: str = "",
    ) -> PredictionReceipt:
        receipt_hash = hashlib.sha256(
            f"{challenge_id}:{prediction.direction}:{prediction.confidence}:{idempotency_key}".encode()
        ).hexdigest()
        receipt = PredictionReceipt(
            challenge_id=challenge_id,
            agent_id="mock_agent",
            direction=prediction.direction,
            confidence=prediction.confidence,
            receipt_hash=receipt_hash,
            status="submitted",
        )
        self.predictions.setdefault(challenge_id, []).append(receipt)
        return receipt

    def get_challenge_result(self, challenge_id: str) -> ChallengeResult | None:
        return self.results.get(challenge_id)

    def get_agent_calibration(self) -> AgentCalibration | None:
        return self.calibration

    def synthesize_prediction(
        self,
        attempt: ARCCandidateAttemptV1,
        challenge: GroundTruthChallenge,
    ) -> DirectionalPrediction:
        return HeadlineArenaClient().synthesize_prediction(attempt, challenge)

    def evaluate_alignment(
        self,
        attempt: ARCCandidateAttemptV1,
        results: list[ChallengeResult],
    ) -> GroundTruthEvaluation:
        return HeadlineArenaClient().evaluate_alignment(attempt, results)
