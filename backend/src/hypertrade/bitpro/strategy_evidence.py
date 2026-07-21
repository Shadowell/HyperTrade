"""Fail-closed consumer for bounded BitPro strategy evidence contracts."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from hypertrade.db import BitProStrategyEvidenceRecord, Database

MCP_CONTRACT_VERSION = "bitpro-mcp-v1"
PRODUCER_VERSION = "bitpro-strategy-evidence-v1"
MAX_POINTS = 500
MAX_MEMBERS = 20
MAX_ERRORS = 20
SUPPORTED_SCHEMAS = {
    "strategy_return_series.v1",
    "aligned_strategy_return_matrix.v1",
    "strategy_execution_quality.v1",
}


class BitProStrategyEvidenceError(ValueError):
    """The external evidence cannot safely enter HyperTrade research state."""


def validate_return_series(
    payload: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    value = _base(payload, "strategy_return_series.v1")
    _require(
        value,
        "source_layer",
        "source_id",
        "strategy_id",
        "strategy_version",
        "config_version",
        "symbols",
        "timeframe",
        "bucket_seconds",
        "timezone",
        "currency",
        "precision",
        "window",
        "cost_model",
        "points",
        "data_gaps",
        "pagination",
        "as_of",
        "freshness",
        "source_hash",
        "recorded_at",
        "content_hash",
    )
    if value["source_layer"] not in {"backtest", "paper", "live"}:
        raise BitProStrategyEvidenceError("unsupported source layer")
    if value["timezone"] != "UTC":
        raise BitProStrategyEvidenceError("return series timezone must be UTC")
    bucket = _integer(value["bucket_seconds"], "bucket_seconds", minimum=60)
    if bucket > 86_400:
        raise BitProStrategyEvidenceError("bucket_seconds exceeds contract limit")
    if not isinstance(value["symbols"], list) or not value["symbols"]:
        raise BitProStrategyEvidenceError("symbols must be a non-empty list")
    _cost_model(value["cost_model"])

    points = value["points"]
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        raise BitProStrategyEvidenceError("return series point count is outside contract")
    timestamps: list[datetime] = []
    for point in points:
        if not isinstance(point, dict):
            raise BitProStrategyEvidenceError("return series point must be an object")
        _require(point, "timestamp", "equity", "gross_return", "net_return")
        timestamps.append(_time(point["timestamp"], "point timestamp"))
        _decimal(point["equity"], "equity")
        _decimal(point["net_return"], "net_return")
        if point["gross_return"] is not None:
            _decimal(point["gross_return"], "gross_return")
    _strictly_increasing(timestamps, "return series timestamps")
    current = _aware(now or datetime.now(UTC), "now")
    if timestamps[-1] > current:
        raise BitProStrategyEvidenceError("future return point is forbidden")
    window = value["window"]
    if not isinstance(window, dict):
        raise BitProStrategyEvidenceError("window must be an object")
    _require(window, "start_at", "end_at")
    start = _time(window["start_at"], "window.start_at")
    end = _time(window["end_at"], "window.end_at")
    if end < start or timestamps[0] < start or timestamps[-1] > end:
        raise BitProStrategyEvidenceError("points fall outside the declared window")
    _not_future(value, current)

    pagination = value["pagination"]
    if not isinstance(pagination, dict):
        raise BitProStrategyEvidenceError("pagination must be an object")
    _require(pagination, "limit", "cursor", "next_cursor", "total_points")
    limit = _integer(pagination["limit"], "pagination.limit", minimum=1)
    total = _integer(pagination["total_points"], "pagination.total_points", minimum=1)
    if limit > MAX_POINTS or total > MAX_POINTS or len(points) > limit:
        raise BitProStrategyEvidenceError("pagination exceeds the 500-point contract")
    for key in ("cursor", "next_cursor"):
        cursor = str(pagination[key])
        if cursor and (not cursor.isdigit() or int(cursor) < 0):
            raise BitProStrategyEvidenceError(f"invalid pagination {key}")
    _verify_content_hash(value, volatile={"freshness", "recorded_at"})

    is_complete = not str(pagination["cursor"]) and not str(pagination["next_cursor"])
    if is_complete:
        if total != len(points):
            raise BitProStrategyEvidenceError("complete series total_points mismatch")
        stable_source = {
            "source_layer": value["source_layer"],
            "source_id": value["source_id"],
            "strategy_id": value["strategy_id"],
            "strategy_version": value["strategy_version"],
            "config_version": value["config_version"],
            "timeframe": value["timeframe"],
            "currency": value["currency"],
            "cost_model": value["cost_model"],
            "points": points,
        }
        if value["source_hash"] != _hash(stable_source):
            raise BitProStrategyEvidenceError("return series source_hash mismatch")
    return value


def validate_aligned_matrix(
    payload: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    value = _base(payload, "aligned_strategy_return_matrix.v1")
    _require(
        value,
        "members",
        "denominator",
        "available_count",
        "missing_members",
        "alignment_method",
        "bucket_seconds",
        "sample_count",
        "timestamps",
        "rows",
        "comparable",
        "reason_codes",
        "source_hashes",
        "as_of",
        "recorded_at",
        "content_hash",
    )
    members = value["members"]
    if not isinstance(members, list) or not 1 <= len(members) <= MAX_MEMBERS:
        raise BitProStrategyEvidenceError("matrix member count is outside contract")
    if len(set(map(str, members))) != len(members):
        raise BitProStrategyEvidenceError("matrix members must be unique")
    denominator = _integer(value["denominator"], "denominator", minimum=1)
    available = _integer(value["available_count"], "available_count", minimum=0)
    if denominator != len(members):
        raise BitProStrategyEvidenceError("matrix denominator does not match members")
    missing = value["missing_members"]
    rows = value["rows"]
    if not isinstance(missing, list) or not isinstance(rows, list):
        raise BitProStrategyEvidenceError("matrix rows and missing_members must be lists")
    if available != len(rows) or available + len(missing) != denominator:
        raise BitProStrategyEvidenceError("matrix silently changed its denominator")
    missing_names: set[str] = set()
    for item in missing:
        if not isinstance(item, dict) or not str(item.get("member", "")) or not str(
            item.get("reason", "")
        ):
            raise BitProStrategyEvidenceError("missing matrix member requires a reason")
        missing_names.add(str(item["member"]))
    row_names = {str(row.get("member", "")) for row in rows if isinstance(row, dict)}
    if row_names | missing_names != set(map(str, members)) or row_names & missing_names:
        raise BitProStrategyEvidenceError("matrix membership projection is inconsistent")
    timestamps = value["timestamps"]
    if not isinstance(timestamps, list) or len(timestamps) > MAX_POINTS:
        raise BitProStrategyEvidenceError("matrix timestamps exceed contract limit")
    parsed = [_time(item, "matrix timestamp") for item in timestamps]
    _strictly_increasing(parsed, "matrix timestamps")
    current = _aware(now or datetime.now(UTC), "now")
    if parsed and parsed[-1] > current:
        raise BitProStrategyEvidenceError("future matrix timestamp is forbidden")
    samples = _integer(value["sample_count"], "sample_count", minimum=0)
    if samples != len(timestamps):
        raise BitProStrategyEvidenceError("matrix sample_count mismatch")
    source_hashes = value["source_hashes"]
    if not isinstance(source_hashes, list) or len(source_hashes) != available:
        raise BitProStrategyEvidenceError("matrix source_hash count mismatch")
    for row in rows:
        if not isinstance(row, dict):
            raise BitProStrategyEvidenceError("matrix row must be an object")
        _require(row, "member", "source_hash", "returns")
        if not isinstance(row["returns"], list) or len(row["returns"]) != samples:
            raise BitProStrategyEvidenceError("matrix row sample count mismatch")
        for item in row["returns"]:
            _decimal(item, "matrix return")
    if bool(value["comparable"]) and (missing or available != denominator or denominator < 2):
        raise BitProStrategyEvidenceError("matrix comparable flag contradicts membership")
    if missing and "missing_member" not in value["reason_codes"]:
        raise BitProStrategyEvidenceError("matrix missing_member reason is required")
    _not_future(value, current)
    _verify_content_hash(value, volatile={"recorded_at"})
    return value


def validate_execution_quality(
    payload: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    value = _base(payload, "strategy_execution_quality.v1")
    _require(
        value,
        "source_layer",
        "source_id",
        "strategy_id",
        "strategy_version",
        "signal_count",
        "order_count",
        "fill_count",
        "fill_ratio",
        "reject_count",
        "cancel_count",
        "latency_ms",
        "slippage",
        "exposure",
        "turnover",
        "data_gaps",
        "errors",
        "as_of",
        "recorded_at",
        "source_hash",
        "content_hash",
    )
    if value["source_layer"] not in {"backtest", "paper", "live"}:
        raise BitProStrategyEvidenceError("unsupported source layer")
    for key in ("signal_count", "order_count", "fill_count", "reject_count", "cancel_count"):
        if value[key] is not None:
            _integer(value[key], key, minimum=0)
    if value["fill_ratio"] is not None:
        ratio = _decimal(value["fill_ratio"], "fill_ratio")
        if ratio < 0 or ratio > 1:
            raise BitProStrategyEvidenceError("fill_ratio must be between zero and one")
    if not isinstance(value["data_gaps"], list):
        raise BitProStrategyEvidenceError("data_gaps must be a list")
    if not isinstance(value["errors"], list) or len(value["errors"]) > MAX_ERRORS:
        raise BitProStrategyEvidenceError("execution errors exceed bounded summary")
    current = _aware(now or datetime.now(UTC), "now")
    _not_future(value, current)
    _verify_content_hash(value, volatile={"recorded_at"})
    return value


class BitProStrategyEvidenceStore:
    """Persist validated summaries and immutable external references, never source points."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def persist(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        schema = str(payload.get("schema_version", ""))
        if schema == "strategy_return_series.v1":
            value = validate_return_series(payload)
            pagination = value["pagination"]
            if str(pagination["cursor"]) or str(pagination["next_cursor"]):
                raise BitProStrategyEvidenceError("only a complete validated series may persist")
            summary = {
                "strategy_id": value["strategy_id"],
                "strategy_version": value["strategy_version"],
                "config_version": value["config_version"],
                "symbols": value["symbols"],
                "timeframe": value["timeframe"],
                "bucket_seconds": value["bucket_seconds"],
                "currency": value["currency"],
                "window": value["window"],
                "point_count": len(value["points"]),
                "gross_return": value["gross_return"],
                "net_return": value["net_return"],
                "cost_model": value["cost_model"],
                "data_gaps": value["data_gaps"],
            }
        elif schema == "aligned_strategy_return_matrix.v1":
            value = validate_aligned_matrix(payload)
            summary = {
                key: value[key]
                for key in (
                    "members",
                    "denominator",
                    "available_count",
                    "missing_members",
                    "alignment_method",
                    "bucket_seconds",
                    "sample_count",
                    "comparable",
                    "reason_codes",
                )
            }
        elif schema == "strategy_execution_quality.v1":
            value = validate_execution_quality(payload)
            summary = {
                key: value[key]
                for key in (
                    "strategy_id",
                    "strategy_version",
                    "signal_count",
                    "order_count",
                    "fill_count",
                    "fill_ratio",
                    "reject_count",
                    "cancel_count",
                    "latency_ms",
                    "slippage",
                    "exposure",
                    "turnover",
                    "data_gaps",
                    "errors",
                )
            }
        else:
            raise BitProStrategyEvidenceError(f"unsupported strategy evidence schema: {schema}")
        refs = {
            "contract_version": value["contract_version"],
            "producer": value["producer"],
            "source_hash": value.get("source_hash", ""),
            "source_hashes": value.get("source_hashes", []),
            "content_hash": value["content_hash"],
        }
        with self.db.session() as session:
            existing = session.scalar(
                select(BitProStrategyEvidenceRecord).where(
                    BitProStrategyEvidenceRecord.content_hash == value["content_hash"]
                )
            )
            if existing is not None:
                return _record(existing, idempotent=True)
            row = BitProStrategyEvidenceRecord(
                schema_version=schema,
                evidence_type=schema.removesuffix(".v1"),
                source_layer=str(value.get("source_layer", "")),
                source_id=str(value.get("source_id", "")),
                source_hash=str(value.get("source_hash", "")),
                content_hash=value["content_hash"],
                as_of=_time(value["as_of"], "as_of"),
                summary_json=summary,
                refs_json=refs,
                created_by=actor,
            )
            session.add(row)
            session.flush()
            return _record(row, idempotent=False)


def _base(payload: dict[str, Any], schema: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BitProStrategyEvidenceError("strategy evidence payload must be an object")
    value = deepcopy(payload)
    if value.get("schema_version") != schema or schema not in SUPPORTED_SCHEMAS:
        raise BitProStrategyEvidenceError("unsupported strategy evidence schema")
    if value.get("contract_version") != MCP_CONTRACT_VERSION:
        raise BitProStrategyEvidenceError("unsupported BitPro MCP contract")
    if value.get("producer") != PRODUCER_VERSION:
        raise BitProStrategyEvidenceError("unsupported strategy evidence producer")
    return value


def _require(value: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise BitProStrategyEvidenceError(f"strategy evidence missing fields: {','.join(missing)}")


def _cost_model(value: Any) -> None:
    if not isinstance(value, dict):
        raise BitProStrategyEvidenceError("cost_model must be an object")
    fees = value.get("fees")
    slippage = value.get("slippage")
    funding = value.get("funding")
    if not isinstance(fees, dict) or fees.get("taker_fee_bps") is None:
        raise BitProStrategyEvidenceError("cost model missing taker fee")
    if not isinstance(slippage, dict) or slippage.get("slippage_bps") is None:
        raise BitProStrategyEvidenceError("cost model missing slippage")
    if not isinstance(funding, dict) or not str(funding.get("mode", "")).strip():
        raise BitProStrategyEvidenceError("cost model missing funding mode")
    _decimal(fees["taker_fee_bps"], "taker_fee_bps")
    _decimal(slippage["slippage_bps"], "slippage_bps")


def _not_future(value: dict[str, Any], now: datetime) -> None:
    for key in ("as_of", "recorded_at"):
        if _time(value[key], key) > now:
            raise BitProStrategyEvidenceError(f"future {key} is forbidden")


def _verify_content_hash(value: dict[str, Any], *, volatile: set[str]) -> None:
    expected = _hash(
        {
            key: item
            for key, item in value.items()
            if key not in volatile | {"content_hash"}
        }
    )
    if value["content_hash"] != expected:
        raise BitProStrategyEvidenceError("strategy evidence content_hash mismatch")


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise BitProStrategyEvidenceError(f"invalid {field}") from exc
    return _aware(parsed, field)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BitProStrategyEvidenceError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BitProStrategyEvidenceError(f"invalid decimal {field}") from exc
    if not parsed.is_finite() or not math.isfinite(float(parsed)):
        raise BitProStrategyEvidenceError(f"non-finite decimal {field}")
    return parsed


def _integer(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise BitProStrategyEvidenceError(f"invalid integer {field}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise BitProStrategyEvidenceError(f"invalid integer {field}") from exc
    if parsed != value or parsed < minimum:
        raise BitProStrategyEvidenceError(f"invalid integer {field}")
    return parsed


def _strictly_increasing(values: list[datetime], field: str) -> None:
    if any(current <= previous for previous, current in zip(values, values[1:], strict=False)):
        raise BitProStrategyEvidenceError(f"{field} must be strictly increasing")


def _record(row: BitProStrategyEvidenceRecord, *, idempotent: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "schema_version": row.schema_version,
        "evidence_type": row.evidence_type,
        "source_layer": row.source_layer,
        "source_id": row.source_id,
        "source_hash": row.source_hash,
        "content_hash": row.content_hash,
        "as_of": row.as_of.isoformat() if row.as_of else None,
        "summary": row.summary_json,
        "refs": row.refs_json,
        "raw_series_persisted": False,
        "execution_authorized": False,
        "idempotent": idempotent,
    }
