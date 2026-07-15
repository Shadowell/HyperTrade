"""Bounded, read-only BitPro evidence capture for portfolio research."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Any, Protocol

from sqlalchemy import desc, select

from hypertrade.db import Database, PortfolioObservationWindow, utc_now
from hypertrade.portfolio.evidence_schemas import (
    PortfolioDataQualityV1,
    PortfolioObservationCaptureV1,
    PortfolioObservationWindowV1,
)
from hypertrade.research.strategy_cards import StrategyCardService

SCHEMA_VERSION = "portfolio_observation_window.v1"
POLICY_VERSION = "portfolio_evidence_policy.v1"


class PortfolioEvidenceReadAdapter(Protocol):
    """The data plane has no mutation method by construction."""

    def health(self) -> dict[str, Any]: ...

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]: ...

    def paper_equity_curve(
        self, *, strategy_id: int | None = None, sample_limit: int = 50
    ) -> dict[str, Any]: ...


class PortfolioEvidenceService:
    """Persist statistical summaries and hashes, never source time-series payloads."""

    def __init__(self, db: Database, *, adapter: PortfolioEvidenceReadAdapter) -> None:
        self.db = db
        self.adapter = adapter

    def capture(
        self,
        payload: PortfolioObservationCaptureV1,
        *,
        actor: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request = payload.model_dump(mode="json", exclude={"idempotency_key"})
        request_hash = _hash(request)
        with self.db.session() as session:
            replay = session.scalar(
                select(PortfolioObservationWindow).where(
                    PortfolioObservationWindow.idempotency_key == payload.idempotency_key
                )
            )
            if replay is not None:
                if replay.request_hash != request_hash:
                    raise ValueError("window idempotency key is bound to another request")
                return {**window_to_dict(replay), "idempotent": True}

        observed_at = _aware(now or utc_now())
        cards = [
            card
            for card in StrategyCardService(self.db).list()
            if card.get("schema_version") == "strategy_card.v2"
        ]
        if payload.strategy_card_ids:
            selected = set(payload.strategy_card_ids)
            cards = [card for card in cards if str(card.get("card_id")) in selected]
            missing_cards = sorted(selected - {str(card.get("card_id")) for card in cards})
        else:
            missing_cards = []

        health_payload, health_ok = self._health()
        summaries: list[dict[str, Any]] = []
        transient_returns: dict[str, dict[str, Decimal]] = {}
        source_cards: list[dict[str, Any]] = []
        all_times: list[datetime] = []
        for card in cards:
            summary, returns, source = self._capture_card(
                card,
                payload=payload,
                observed_at=observed_at,
                source_healthy=health_ok,
            )
            summaries.append(summary)
            transient_returns[summary["card_id"]] = returns
            source_cards.append(source)
            all_times.extend(
                parsed
                for value in (summary.get("sample_start"), summary.get("sample_end"))
                if value and (parsed := _parse_timestamp(value)) is not None
            )

        pairwise = _pairwise(summaries, transient_returns, payload)
        quality = _quality(
            summaries,
            denominator=len(cards) + len(missing_cards),
            missing_cards=missing_cards,
            source_healthy=health_ok,
        )
        source_refs = {
            "adapter": "bitpro_mcp",
            "read_tools": ["bitpro_health", "paper_snapshot", "paper_equity_curve"],
            "health_content_hash": _hash(health_payload),
            "strategy_sources": source_cards,
            "missing_card_ids": missing_cards,
        }
        source_hash = _hash(source_refs)
        window_start = min(all_times) if all_times else None
        content = PortfolioObservationWindowV1(
            status=quality.status,
            horizon_days=payload.horizon_days,
            bucket_minutes=payload.bucket_minutes,
            window_start=window_start.isoformat() if window_start else None,
            window_end=observed_at.isoformat(),
            source_refs=source_refs,
            quality=quality,
            strategies=summaries,
            pairwise=pairwise,
        ).model_dump(mode="json")
        # Capture time is audit metadata, not source content. Reuse an unchanged
        # request/source/quality projection instead of creating a timer-driven row.
        content_hash = _hash(
            {
                "request_hash": request_hash,
                "source_hash": source_hash,
                "quality": content["quality"],
                "strategies": content["strategies"],
                "pairwise": content["pairwise"],
            }
        )

        with self.db.session() as session:
            duplicate = session.scalar(
                select(PortfolioObservationWindow).where(
                    PortfolioObservationWindow.content_hash == content_hash
                )
            )
            if duplicate is not None:
                return {**window_to_dict(duplicate), "idempotent_content": True}
            row = PortfolioObservationWindow(
                schema_version=SCHEMA_VERSION,
                policy_version=POLICY_VERSION,
                status=quality.status,
                horizon_days=payload.horizon_days,
                bucket_minutes=payload.bucket_minutes,
                window_start=window_start,
                window_end=observed_at,
                request_hash=request_hash,
                source_hash=source_hash,
                content_hash=content_hash,
                idempotency_key=payload.idempotency_key,
                source_refs_json=source_refs,
                quality_json=quality.model_dump(mode="json"),
                strategy_summaries_json=summaries,
                pairwise_json=pairwise,
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return window_to_dict(row)

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.scalars(
                select(PortfolioObservationWindow)
                .order_by(desc(PortfolioObservationWindow.created_at))
                .limit(max(1, min(limit, 500)))
            ).all()
            return [window_to_dict(row) for row in rows]

    def get(self, window_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(PortfolioObservationWindow, window_id)
            if row is None:
                raise KeyError(window_id)
            return window_to_dict(row)

    def latest(self) -> dict[str, Any] | None:
        rows = self.list(limit=1)
        return rows[0] if rows else None

    def diff(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_rows = {row["card_id"]: row for row in left["strategies"]}
        right_rows = {row["card_id"]: row for row in right["strategies"]}
        return {
            "schema_version": "portfolio_observation_diff.v1",
            "left_id": left_id,
            "right_id": right_id,
            "status_change": {"from": left["status"], "to": right["status"]},
            "added_card_ids": sorted(set(right_rows) - set(left_rows)),
            "removed_card_ids": sorted(set(left_rows) - set(right_rows)),
            "strategy_status_changes": [
                {
                    "card_id": card_id,
                    "from": left_rows[card_id]["status"],
                    "to": right_rows[card_id]["status"],
                }
                for card_id in sorted(set(left_rows) & set(right_rows))
                if left_rows[card_id]["status"] != right_rows[card_id]["status"]
            ],
            "quality_change": {
                "coverage_ratio": {
                    "from": left["quality"]["coverage_ratio"],
                    "to": right["quality"]["coverage_ratio"],
                }
            },
            "content_hash_changed": left["content_hash"] != right["content_hash"],
        }

    def _health(self) -> tuple[dict[str, Any], bool]:
        try:
            result = dict(self.adapter.health())
        except Exception as exc:  # connector failures become bounded quality facts
            return {"status": "error", "error_type": type(exc).__name__}, False
        return result, str(result.get("status", "")).lower() in {"ok", "healthy", "available"}

    def _capture_card(
        self,
        card: dict[str, Any],
        *,
        payload: PortfolioObservationCaptureV1,
        observed_at: datetime,
        source_healthy: bool,
    ) -> tuple[dict[str, Any], dict[str, Decimal], dict[str, Any]]:
        card_id = str(card["card_id"])
        strategy_id_text = str(card.get("bitpro_strategy_id", ""))
        unknowns: list[str] = []
        try:
            strategy_id = int(strategy_id_text) if strategy_id_text else None
        except ValueError:
            strategy_id = None
            unknowns.append("invalid_bitpro_strategy_id")
        if strategy_id is None:
            unknowns.append("paper_identity_unavailable")
        if not source_healthy:
            unknowns.append("bitpro_source_unhealthy")

        curve: dict[str, Any] = {}
        snapshot: dict[str, Any] = {}
        if strategy_id is not None and source_healthy:
            try:
                snapshot = dict(self.adapter.paper_snapshot(strategy_id=strategy_id))
            except Exception as exc:  # no connector payload or exception is persisted
                unknowns.append(f"bitpro_snapshot_read_failed:{type(exc).__name__}")
            try:
                curve = dict(
                    self.adapter.paper_equity_curve(
                        strategy_id=strategy_id,
                        sample_limit=payload.max_points,
                    )
                )
            except Exception as exc:  # no connector payload or exception is persisted
                unknowns.append(f"bitpro_curve_read_failed:{type(exc).__name__}")

        curve_hash = _hash(curve)
        snapshot_hash = _hash(snapshot)
        points, point_gaps = _bounded_points(
            curve.get("equity_curve", []),
            observed_at=observed_at,
            horizon_days=payload.horizon_days,
            bucket_minutes=payload.bucket_minutes,
            max_points=payload.max_points,
        )
        unknowns.extend(point_gaps)
        returns = _returns(points)
        sample_times = sorted(points)
        latest = _parse_timestamp(sample_times[-1]) if sample_times else None
        freshness = (
            "fresh"
            if latest is not None
            and observed_at - latest <= timedelta(minutes=payload.freshness_minutes)
            else "stale"
            if latest is not None
            else "unknown"
        )
        if freshness == "stale":
            unknowns.append("source_stale")
        if len(returns) < payload.min_aligned_returns:
            unknowns.append("insufficient_returns")

        if strategy_id is None:
            status = "no_window"
        elif not source_healthy or any(
            value.startswith("bitpro_curve_read_failed") for value in unknowns
        ):
            status = "source_unhealthy"
        elif freshness == "stale":
            status = "stale"
        elif len(returns) < payload.min_aligned_returns:
            status = "insufficient"
        else:
            status = "available"

        source_ref = {
            "card_id": card_id,
            "card_snapshot_id": card.get("snapshot_id", ""),
            "manifest_id": dict(card.get("source_refs", {})).get("manifest_id", ""),
            "version_id": dict(card.get("version", {})).get("id", ""),
            "bitpro_strategy_id": strategy_id_text,
            "curve_content_hash": curve_hash,
            "snapshot_content_hash": snapshot_hash,
        }
        metrics = _metrics(points, returns)
        metrics.update(
            {
                "capacity": str(card.get("capacity", "unknown")),
                "liquidity": str(card.get("liquidity", "unknown")),
                "risk_contribution": "unknown",
                "risk_contribution_unknown_reason": "portfolio_weights_unavailable",
            }
        )
        if metrics["capacity"] == "unknown":
            unknowns.append("capacity_unavailable")
        if metrics["liquidity"] == "unknown":
            unknowns.append("liquidity_unavailable")
        unknowns.append("portfolio_weights_unavailable")
        summary = {
            "card_id": card_id,
            "strategy_key": str(card.get("strategy_key", "")),
            "version_id": dict(card.get("version", {})).get("id", ""),
            "bitpro_strategy_id": strategy_id_text,
            "status": status,
            "horizon_days": payload.horizon_days,
            "bucket_minutes": payload.bucket_minutes,
            "sample_count": len(returns),
            "level_count": len(points),
            "sample_start": sample_times[0] if sample_times else None,
            "sample_end": sample_times[-1] if sample_times else None,
            "freshness": freshness,
            "metrics": metrics,
            "exposures": {
                "symbols": list(card.get("allowed_symbols", [])),
                "timeframes": list(card.get("allowed_timeframes", [])),
                "factors": list(card.get("strategy_category", [])),
                "direction": str(card.get("direction_exposure", "unknown")),
            },
            "unknown_reasons": sorted(set(unknowns)),
            "source_refs": source_ref,
        }
        return summary, returns, source_ref


def window_to_dict(row: PortfolioObservationWindow) -> dict[str, Any]:
    return {
        "id": row.id,
        "schema_version": row.schema_version,
        "policy_version": row.policy_version,
        "status": row.status,
        "horizon_days": row.horizon_days,
        "bucket_minutes": row.bucket_minutes,
        "window_start": row.window_start.isoformat() if row.window_start else None,
        "window_end": row.window_end.isoformat(),
        "request_hash": row.request_hash,
        "source_hash": row.source_hash,
        "content_hash": row.content_hash,
        "source_refs": dict(row.source_refs_json or {}),
        "quality": dict(row.quality_json or {}),
        "strategies": list(row.strategy_summaries_json or []),
        "pairwise": list(row.pairwise_json or []),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
        "execution_authorized": False,
        "raw_series_persisted": False,
    }


def _quality(
    summaries: list[dict[str, Any]],
    *,
    denominator: int,
    missing_cards: list[str],
    source_healthy: bool,
) -> PortfolioDataQualityV1:
    identity_count = sum(bool(row["bitpro_strategy_id"]) for row in summaries)
    fetched_count = sum(row["status"] not in {"no_window", "source_unhealthy"} for row in summaries)
    available = sum(row["status"] == "available" for row in summaries)
    source_unhealthy = sum(row["status"] == "source_unhealthy" for row in summaries)
    stale = sum(row["status"] == "stale" for row in summaries)
    insufficient = sum(row["status"] == "insufficient" for row in summaries)
    if denominator == 0:
        status = "no_cards"
    elif not source_healthy or (source_unhealthy and not available):
        status = "source_unhealthy"
    elif identity_count == 0:
        status = "no_window"
    elif available:
        status = "available"
    elif stale and stale == fetched_count:
        status = "stale"
    else:
        status = "insufficient"
    coverage = Decimal(available) / Decimal(denominator) if denominator else Decimal(0)
    gaps = [f"strategy_card.{card_id}.missing" for card_id in missing_cards]
    gaps.extend(
        f"strategy.{row['card_id']}.{reason}"
        for row in summaries
        for reason in row["unknown_reasons"]
    )
    return PortfolioDataQualityV1(
        status=status,
        denominator=denominator,
        identity_count=identity_count,
        fetched_count=fetched_count,
        available_count=available,
        stale_count=stale,
        insufficient_count=insufficient,
        coverage_ratio=_decimal_text(coverage),
        gaps=sorted(set(gaps)),
    )


def _bounded_points(
    rows: Any,
    *,
    observed_at: datetime,
    horizon_days: int,
    bucket_minutes: int,
    max_points: int,
) -> tuple[dict[str, Decimal], list[str]]:
    if not isinstance(rows, list):
        return {}, ["equity_curve_invalid"]
    cutoff = observed_at - timedelta(days=horizon_days)
    buckets: dict[str, tuple[datetime, Decimal]] = {}
    gaps: list[str] = []
    for raw in rows[:max_points]:
        if not isinstance(raw, dict):
            gaps.append("equity_point_invalid")
            continue
        timestamp = _parse_timestamp(raw.get("timestamp"))
        equity = _decimal(raw.get("equity"))
        if timestamp is None or equity is None or equity <= 0:
            gaps.append("equity_point_invalid")
            continue
        if timestamp > observed_at:
            gaps.append("future_timestamp_rejected")
            continue
        if timestamp < cutoff:
            continue
        bucket = _bucket(timestamp, bucket_minutes)
        previous = buckets.get(bucket)
        if previous is None or timestamp > previous[0]:
            buckets[bucket] = (timestamp, equity)
    points = {key: value[1] for key, value in sorted(buckets.items())}
    return points, gaps


def _returns(points: dict[str, Decimal]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    previous: Decimal | None = None
    for key, equity in sorted(points.items()):
        if previous is not None and previous > 0:
            result[key] = (equity / previous) - Decimal(1)
        previous = equity
    return result


def _metrics(points: dict[str, Decimal], returns: dict[str, Decimal]) -> dict[str, str]:
    values = [points[key] for key in sorted(points)]
    return_values = [returns[key] for key in sorted(returns)]
    total_return = (
        ((values[-1] / values[0]) - Decimal(1)) * Decimal(100)
        if len(values) >= 2 and values[0] != 0
        else None
    )
    volatility = _sample_stddev(return_values)
    peak: Decimal | None = None
    max_drawdown = Decimal(0)
    for value in values:
        peak = value if peak is None or value > peak else peak
        if peak > 0:
            max_drawdown = max(max_drawdown, ((peak - value) / peak) * Decimal(100))
    return {
        "total_return_pct": _decimal_text(total_return) if total_return is not None else "unknown",
        "volatility_proxy": _decimal_text(volatility) if volatility is not None else "unknown",
        "max_drawdown_pct": _decimal_text(max_drawdown) if values else "unknown",
    }


def _pairwise(
    summaries: list[dict[str, Any]],
    returns: dict[str, dict[str, Decimal]],
    payload: PortfolioObservationCaptureV1,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for left, right in combinations(summaries, 2):
        left_id = str(left["card_id"])
        right_id = str(right["card_id"])
        common = sorted(set(returns[left_id]) & set(returns[right_id]))
        correlation: Decimal | None = None
        reason = ""
        if left["status"] != "available" or right["status"] != "available":
            reason = "strategy_window_unavailable"
        elif len(common) < payload.min_aligned_returns:
            reason = "insufficient_aligned_returns"
        else:
            correlation = _correlation(
                [returns[left_id][key] for key in common],
                [returns[right_id][key] for key in common],
            )
            if correlation is None:
                reason = "zero_variance_or_invalid_series"
        result.append(
            {
                "left_card_id": left_id,
                "right_card_id": right_id,
                "status": "available" if correlation is not None else "unknown",
                "correlation": _decimal_text(correlation) if correlation is not None else None,
                "sample_count": len(common),
                "sample_start": common[0] if common else None,
                "sample_end": common[-1] if common else None,
                "horizon_days": payload.horizon_days,
                "bucket_minutes": payload.bucket_minutes,
                "unknown_reason": reason,
                "shared_exposures": _shared_exposures(left, right),
                "source_hashes": sorted(
                    {
                        left["source_refs"]["curve_content_hash"],
                        right["source_refs"]["curve_content_hash"],
                    }
                ),
            }
        )
    return result


def _shared_exposures(left: dict[str, Any], right: dict[str, Any]) -> dict[str, list[str]]:
    left_exp = dict(left["exposures"])
    right_exp = dict(right["exposures"])
    return {
        key: sorted(set(left_exp.get(key, [])) & set(right_exp.get(key, [])))
        for key in ("symbols", "timeframes", "factors")
    }


def _correlation(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    count = Decimal(len(left))
    left_mean = sum(left, Decimal(0)) / count
    right_mean = sum(right, Decimal(0)) / count
    covariance = sum(
        ((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)),
        Decimal(0),
    )
    left_ss = sum(((value - left_mean) ** 2 for value in left), Decimal(0))
    right_ss = sum(((value - right_mean) ** 2 for value in right), Decimal(0))
    denominator = (left_ss * right_ss).sqrt()
    if denominator == 0:
        return None
    return max(Decimal(-1), min(Decimal(1), covariance / denominator))


def _sample_stddev(values: list[Decimal]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal(0)) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal(0)) / Decimal(
        len(values) - 1
    )
    return variance.sqrt()


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            numeric = float(value)
            return datetime.fromtimestamp(numeric / 1000 if numeric > 10**11 else numeric, tz=UTC)
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (OverflowError, OSError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _bucket(value: datetime, minutes: int) -> str:
    seconds = minutes * 60
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=UTC).isoformat()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001")), "f")


def _hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
