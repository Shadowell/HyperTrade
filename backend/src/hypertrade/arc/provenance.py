"""Bounded source metadata is distinct from window coverage and execution authority."""

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any

REASONS = {
    "historical_cost_metadata_missing",
    "invalid_research_costs",
    "historical_code_version_missing",
    "execution_version_unverified",
    "review_binding_invalid",
    "started_at_missing",
}


def alert_codes(value: Any) -> list[str]:
    """Project only fixed source failures; old reports without provenance stay compatible."""
    if value is None:
        return []
    if isinstance(value, dict):
        status, reasons = value.get("status"), value.get("blocking_reasons")
        if status == "verified" and reasons == []:
            return []
        if (
            status == "unknown"
            and isinstance(reasons, list)
            and 0 < len(reasons) <= len(REASONS)
            and all(isinstance(reason, str) and reason in REASONS for reason in reasons)
        ):
            return sorted(set(reasons))
    return ["source_provenance_unavailable"]


def unavailable() -> dict[str, Any]:
    return {
        "status": "unavailable",
        "blocking_reasons": ["source_provenance_unavailable"],
        "window_coverage_verified": False,
        "historical_backfill": False,
    }


def project_provenance(raw: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Only authenticated adapter data with matching immutable IDs may be projected."""
    try:
        encoded = json.dumps(
            raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if len(encoded.encode()) > 32000 or not isinstance(raw, dict):
            return unavailable()
        body = {k: v for k, v in raw.items() if k != "source_hash"}
        expected = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
                ).encode()
            ).hexdigest()
        )
        if (
            raw["contract_version"] != "paper_provenance.v1"
            or raw["source_hash"] != expected
            or raw["read_only"] is not True
            or raw["historical_backfill"] is not False
            or raw["window_coverage_verified"] is not False
            or raw["source_snapshot"] not in {"forward_evidence_snapshot", "paper_session_snapshot"}
        ):
            return unavailable()
        identity = raw["identity"]
        for field, key in [
            ("session_id", "instance_id"),
            ("strategy_id", "strategy_id"),
            ("strategy_version", "strategy_version"),
            ("config_version", "config_version"),
        ]:
            value, wanted = identity[field], snapshot.get(key)
            if (
                isinstance(value, bool)
                or isinstance(wanted, bool)
                or not wanted
                or str(value) != str(wanted)
                or not re.fullmatch(r"[\w.:/-]{1,128}", str(value))
            ):
                return unavailable()
        reasons = raw["blocking_reasons"]
        if (
            not isinstance(reasons, list)
            or len(reasons) > len(REASONS)
            or any(not isinstance(r, str) or r not in REASONS for r in reasons)
        ):
            return unavailable()
        costs = raw["research_costs"]
        known_costs = costs["status"] == "supported"
        cost_hash = costs.get("hash")
        if known_costs:
            if not re.fullmatch(r"[a-f0-9]{64}", str(cost_hash)):
                return unavailable()
            values = costs["values"]
            for key in ("maker_fee_bps", "taker_fee_bps", "slippage_bps"):
                value = values[key]
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    return unavailable()
            if values["funding_mode"] not in {"not_modeled", "strategy_defined_or_not_modeled"}:
                return unavailable()
        elif costs["status"] not in {"unknown", "invalid"} or cost_hash is not None:
            return unavailable()
        code = identity.get("code_sha256")
        if code is not None and not re.fullmatch(r"[a-f0-9]{64}", str(code)):
            return unavailable()
        if identity["assurance"] not in {"review_bound", "snapshot_only", "invalid"}:
            return unavailable()
        started = identity.get("started_at")
        if (
            started is not None
            and datetime.fromisoformat(started.replace("Z", "+00:00")).tzinfo is None
        ):
            return unavailable()
        verified = (
            known_costs
            and identity["assurance"] == "review_bound"
            and bool(code)
            and bool(started)
            and not reasons
        )
        if raw["status"] != ("verified" if verified else "unknown"):
            return unavailable()
        return {
            "status": raw["status"],
            "blocking_reasons": sorted(set(reasons)),
            "identity": {
                key: identity.get(key)
                for key in (
                    "session_id",
                    "strategy_id",
                    "strategy_version",
                    "config_version",
                    "code_sha256",
                    "started_at",
                    "assurance",
                )
            },
            "cost_policy_hash": cost_hash,
            "cost_status": costs["status"],
            "source_hash": expected,
            "source_snapshot": raw["source_snapshot"],
            "window_coverage_verified": False,
            "historical_backfill": False,
        }
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        return unavailable()
