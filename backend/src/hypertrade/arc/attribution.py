"""Descriptive Paper diagnostics. Missing upstream capabilities stay unknown."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

DIMENSIONS = {
    "entry_timing": ["signal_at", "entry_at", "signal_ref"],
    "exit_timing": ["gross_pnl", "mfe_pnl", "path_ref", "path_complete"],
    "costs": ["gross_pnl", "net_pnl", "fees", "slippage", "funding"],
    "long_short": ["side", "net_pnl"],
    "holding_duration": ["entry_at", "exit_at"],
    "sample_coverage": ["coverage.pagination_complete", "coverage.record_count", "source_ref"],
    "regime": ["regime", "regime_ref", "regime_method"],
}

CAPABILITY_FIELDS = {
    "entry_timing": ("entry_benchmark", "signal_ref"),
    "exit_timing": ("round_trip", "mfe", "path_ref"),
    "costs": ("slippage", "funding", "period_fee_turnover_accounting", "gross_net_pnl"),
    "long_short": ("round_trip", "gross_net_pnl"),
    "holding_duration": ("round_trip",),
    "regime": ("regime", "regime_market_ref"),
}


def _identifier(value: Any) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[\w.:/-]{1,128}", value) else None


def _strategy_identifier(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    return value if isinstance(value, str) and value.isdigit() and int(value) > 0 else None


def _aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def attribution_report(
    snapshot: dict[str, Any], now: datetime, evidence: Any = None
) -> dict[str, Any]:
    """No metrics are inferred from legacy trade lists or current fee settings."""
    end = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    scope: dict[str, Any] = {
        "strategy_id": _strategy_identifier(snapshot.get("strategy_id")),
        "session_id": _identifier(snapshot.get("instance_id")),
        "strategy_version": _identifier(snapshot.get("strategy_version")),
        "config_version": _identifier(snapshot.get("config_version")),
        "start_at": (end - timedelta(days=14)).isoformat(),
        "end_at": end.isoformat(),
        "cost_policy_hash": None,
        "trade_refs": [],
        "equity_refs": [],
        "backtest_refs": [],
    }
    report: dict[str, Any] = {
        "schema_version": "paper_attribution.v1",
        "semantics": "descriptive_execution_coverage_only",
        "causal_conclusion": "not_established",
        "scope": scope,
        "dimensions": {
            name: {
                "state": "unknown",
                "reason": "paper_evidence_unavailable",
                "metrics": {},
                "required_fields": fields,
            }
            for name, fields in DIMENSIONS.items()
        },
        "required_contract": "paper_evidence.v1",
        "required_common_fields": [
            "identity.session_id",
            "identity.strategy_id",
            "identity.strategy_version",
            "identity.config_version",
            "window.start_ms",
            "window.end_ms",
            "research_costs.status",
            "research_costs.hash",
            "source_hash",
            "content_hash",
            "coverage",
            "items",
            "next_cursor",
        ],
    }
    if evidence is not None:
        try:
            _bind_coverage(report, evidence)
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
            RecursionError,
        ) as exc:
            allowed = {
                "unsupported_contract",
                "window_mismatch",
                "identity_mismatch",
                "cost_unknown",
                "incomplete_pagination",
                "legacy_unattributed",
                "coverage_unverified",
                "invalid_reference",
                "outside_window",
                "invalid_metric",
                "duplicate_reference",
                "invalid_hash",
                "evidence_budget_exceeded",
            }
            reason = str(exc) if str(exc) in allowed else "malformed_evidence"
            for dimension in report["dimensions"].values():
                dimension["reason"] = reason
    digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    return {**report, "report_id": digest}


def _bind_coverage(report: dict[str, Any], evidence: Any) -> None:
    """Execution ledgers cannot prove round-trip timing or gross/net attribution."""
    scope = report["scope"]
    window = {
        key + "_ms": int(datetime.fromisoformat(scope[key + "_at"]).timestamp() * 1000)
        for key in ("start", "end")
    }
    refs: dict[str, list[str]] = {}
    hashes = {}
    field_states: dict[str, list[Any]] = {}
    cost_hash = None
    first_identity = None
    for kind in ("trades", "equity"):
        page = evidence[kind]
        # Tool results are data: never project arbitrary text or non-finite values.
        if len(json.dumps(page, allow_nan=False)) > 256_000:
            raise ValueError("evidence_budget_exceeded")
        identity, coverage = page["identity"], page["coverage"]
        cost = page["research_costs"]
        if page["contract_version"] != "paper_evidence.v1":
            raise ValueError("unsupported_contract")
        if page["window"] != window:
            raise ValueError("window_mismatch")
        if identity.get("assurance") != "review_bound" or (
            first_identity is not None and identity != first_identity
        ):
            raise ValueError("identity_mismatch")
        if not re.fullmatch(r"[a-f0-9]{64}", str(identity.get("code_sha256"))):
            raise ValueError("identity_mismatch")
        started_at = _aware_time(identity.get("started_at"))
        if started_at is None or started_at.timestamp() * 1000 >= window["end_ms"]:
            raise ValueError("identity_mismatch")
        started_ms = started_at.timestamp() * 1000
        first_identity = identity
        if any(
            not scope[k] or str(identity[k]) != scope[k]
            for k in ("session_id", "strategy_id", "strategy_version", "config_version")
        ):
            raise ValueError("identity_mismatch")
        if (
            cost["status"] != "supported"
            or not re.fullmatch(r"[a-f0-9]{64}", str(cost["hash"]))
            or (cost_hash is not None and cost["hash"] != cost_hash)
        ):
            raise ValueError("cost_unknown")
        if coverage["pagination_complete"] is not True or page.get("next_cursor") is not None:
            raise ValueError("incomplete_pagination")
        if (
            type(coverage["legacy_unattributed_count"]) is not int
            or coverage["legacy_unattributed_count"] != 0
        ):
            raise ValueError("legacy_unattributed")
        if coverage.get("reasons") != []:
            raise ValueError("coverage_unverified")
        for field, state in coverage.get("fields", {}).items():
            if field in {name for fields in CAPABILITY_FIELDS.values() for name in fields}:
                field_states.setdefault(field, []).append(state)
        cost_hash = cost["hash"]
        items = page["items"]
        if (
            not isinstance(items, list)
            or len(items) > 500
            or type(coverage["record_count"]) is not int
            or type(coverage["returned_count"]) is not int
            or coverage["record_count"] != len(items)
            or coverage["returned_count"] != len(items)
        ):
            raise ValueError("incomplete_pagination")
        current_refs = []
        for item in items:
            ref = _identifier(item["source_ref"])
            if (
                not ref
                or not _identifier(str(item["evidence_id"]))
                or _aware_time(item.get("recorded_at")) is None
            ):
                raise ValueError("invalid_reference")
            stamp = item["timestamp"]
            if (
                type(stamp) not in (int, float)
                or not math.isfinite(stamp)
                or not window["start_ms"] <= stamp < window["end_ms"]
                or stamp < started_ms
            ):
                raise ValueError("outside_window")
            for key in ("price", "quantity", "fee", "pnl", "equity"):
                if key in item and (
                    type(item[key]) not in (int, float) or not math.isfinite(item[key])
                ):
                    raise ValueError("invalid_metric")
            current_refs.append(ref)
        if len(current_refs) != len(set(current_refs)):
            raise ValueError("duplicate_reference")
        refs[kind] = current_refs
        hashes[kind] = {k: page[k] for k in ("source_hash", "content_hash")}
        if any(not re.fullmatch(r"sha256:[a-f0-9]{64}", str(v)) for v in hashes[kind].values()):
            raise ValueError("invalid_hash")
    # Commit only after both evidence pages pass; no partial numeric conclusions.
    scope.update(
        cost_policy_hash=cost_hash,
        trade_refs=refs["trades"],
        equity_refs=refs["equity"],
        evidence_hashes=hashes,
    )
    report["dimensions"]["sample_coverage"].update(
        state="observed",
        reason="complete_execution_ledger_window",
        metrics={
            "execution_count": len(refs["trades"]),
            "equity_sample_count": len(refs["equity"]),
        },
    )
    for name, dimension in report["dimensions"].items():
        if name != "sample_coverage":
            dimension["reason"] = "paper_evidence_v1_dimension_unsupported"
        if name in CAPABILITY_FIELDS:
            dimension["source_field_states"] = {
                field: "unknown"
                if field_states.get(field) == ["unknown", "unknown"]
                else "unverified"
                for field in CAPABILITY_FIELDS[name]
            }


def collect_attribution(client: Any, snapshot: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Two bounded GETs; incomplete pagination remains unknown, never a trading action."""
    empty = attribution_report(snapshot, now)
    scope = empty["scope"]
    if not all(scope[k] for k in ("session_id", "strategy_version", "config_version")):
        return empty
    try:
        pages = {
            kind: client.paper_evidence(
                session_id=scope["session_id"],
                kind=kind,
                start_ms=int(datetime.fromisoformat(scope["start_at"]).timestamp() * 1000),
                end_ms=int(datetime.fromisoformat(scope["end_at"]).timestamp() * 1000),
                expected_config_version=scope["config_version"],
                limit=500,
            )
            for kind in ("trades", "equity")
        }
        return attribution_report(snapshot, now, pages)
    except Exception:
        return empty


def read_attribution(strategy_id: int) -> dict[str, Any]:
    """On-demand projection only: no cycle, mission, order or database writes."""
    from hypertrade.arc.observation import _snapshot_body
    from hypertrade.bitpro.mcp import BitProToolAdapter
    from hypertrade.bitpro.paced_reads import PacedReadClient

    now = datetime.now(UTC)
    transport = PacedReadClient()
    client = BitProToolAdapter(transport)
    try:
        snapshot = _snapshot_body(client.paper_snapshot(strategy_id=strategy_id))
        if str(snapshot.get("strategy_id")) != str(strategy_id):
            raise ValueError("snapshot_identity_mismatch")
        return collect_attribution(client, snapshot, now)
    except Exception:
        return attribution_report({"strategy_id": strategy_id}, now)
    finally:
        transport.http_client.close()
