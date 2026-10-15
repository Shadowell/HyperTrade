#!/usr/bin/env python3
"""Bind audited legacy interrupted jobs to their original pending development action.

Default is dry-run. Input must come from a read-only BitPro ledger/frozen-job audit.
Keep a host backup of the mission before applying inside a disposable container.
"""

import argparse
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from hypertrade.arc.backtest_recovery import action_identity, digest
from hypertrade.arc.controller import ARCController, ARCEventV1
from hypertrade.arc.self_test import _experiment_scope, _window_backtest_key
from hypertrade.arc.store import configure_store, get_controller, research_lock
from hypertrade.arc.universe import candidate_symbols
from hypertrade.bitpro.mcp import (
    BitProToolAdapter,
    _normalize_bitpro_spot_symbol,
    _normalize_bitpro_timeframe,
)
from hypertrade.config import get_settings
from hypertrade.db import Database


def binding(controller, audit, job):
    p = controller.projection
    identity = action_identity(p)
    if digest(identity) != audit["action_hash"]:
        raise ValueError("pending action changed since audit")
    attempt = next(a for a in p.attempts if a.attempt_id == identity["attempt_id"])
    goal = p.goal
    if identity["name"] != "develop" or not goal or not goal.research_windows:
        raise ValueError("only window-bound development may be recovered")
    if (
        audit["parent_strategy_id"] != attempt.strategy_spec.get("parent_strategy_id")
        or audit["purpose"] != "baseline"
    ):
        raise ValueError("baseline variant lineage mismatch")
    if (
        job["job_id"] != audit["job_id"]
        or job.get("input_snapshot_hash") != audit["input_snapshot_hash"]
    ):
        raise ValueError("frozen job differs from audit")
    symbols = candidate_symbols(attempt.strategy_spec, goal.symbols)
    timeframe = str(attempt.strategy_spec.get("timeframe") or goal.timeframes[0])
    start, end = goal.research_windows.window("development")
    scope = _experiment_scope(
        goal, attempt.strategy_code, symbols, timeframe, attempt.strategy_spec, {}
    )
    if audit["baseline_create_key"] != "arc-selftest-create-" + scope:
        raise ValueError("baseline experiment scope differs")
    request = {
        "strategy_id": audit["baseline_strategy_id"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "initial_capital": float(goal.paper_initial_equity),
        "symbol": symbols[0] if len(symbols) == 1 else None,
        "timeframe": timeframe,
        "idempotency_key": _window_backtest_key(scope, "development", start, end, goal),
    }
    original = audit["request"]
    if (
        str(job["strategy_id"]) != str(request["strategy_id"])
        or any(original[k] != request[k] for k in ("strategy_id", "start_date", "end_date"))
        or Decimal(str(original["initial_capital"])) != Decimal(str(request["initial_capital"]))
        or original.get("symbol")
        != (_normalize_bitpro_spot_symbol(request["symbol"]) if request["symbol"] else None)
        or original.get("timeframe") != _normalize_bitpro_timeframe(timeframe)
    ):
        raise ValueError("audited request differs from research window/capital/scope")
    entry = {
        "action": identity,
        "request": request,
        "request_hash": digest(request),
        "job_id": job["job_id"],
        "input_snapshot_hash": job["input_snapshot_hash"],
        "phase": "submitted",
        "resume_attempts": 0,
        "read_failures": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "next_check_at": (datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
    }
    return {
        "key": digest([identity["tool_call_id"], request["idempotency_key"]]),
        "entry": entry,
        "charge_event_id": audit["charge_event_id"],
        "audit": {"sha256": digest(audit), "original_job_id": job["job_id"]},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path, default=Path("/app/data/backups"))
    args = parser.parse_args()
    configure_store(Database(str(get_settings().database_url)))
    client = BitProToolAdapter()
    for audit in json.loads(args.audit.read_text()):
        mid = audit["mission_id"]
        with research_lock(mid) as owner:
            if owner is None:
                raise RuntimeError("mission research is active")
            controller = get_controller(mid)
            if controller is None:
                raise ValueError("mission missing")
            if any(
                e.get("job_id") == audit["job_id"]
                and e.get("input_snapshot_hash") == audit["input_snapshot_hash"]
                for e in controller.projection.avo.get("backtest_effects", {}).values()
            ):
                print(json.dumps({"mission": mid, "status": "already_bound"}))
                continue
            job = client.backtest_get_job(job_id=audit["job_id"])["job"]
            payload = binding(controller, audit, job)
            probe = ARCController(mission_id=mid)
            probe.rebase(controller.projection.model_copy(deep=True), controller.revision)
            probe.absorb(
                ARCEventV1(
                    mission_id=mid, event_type="avo_backtest_recovery_bound", payload=payload
                )
            )
            backup = None
            if args.apply:
                args.backup_dir.mkdir(parents=True, exist_ok=True)
                backup = (
                    args.backup_dir
                    / f"{mid}-backtest-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
                )
                backup.touch(mode=0o600, exist_ok=False)
                backup.write_text(controller.projection.model_dump_json())
                owner()
                controller.apply_event("avo_backtest_recovery_bound", payload)
            print(
                json.dumps(
                    {
                        "mission": mid,
                        "job_id": job["job_id"],
                        "status": "bound" if args.apply else "verified_dry_run",
                        "backup": str(backup) if backup else None,
                    }
                )
            )


if __name__ == "__main__":
    main()
