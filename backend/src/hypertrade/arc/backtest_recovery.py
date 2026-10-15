"""Action-bound backtest checkpoints. Resume frozen jobs, never reconstruct success."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn


class BacktestDeferred(Exception):
    """An acknowledged experiment is still pending; the worker may read it later."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def action_identity(projection: Any) -> dict[str, Any]:
    pending = projection.avo.get("pending") or {}
    attempt_id = (pending.get("arguments") or {}).get("attempt_id")
    candidate = next((a for a in projection.attempts if a.attempt_id == attempt_id), None)
    if (
        pending.get("kind") != "tool"
        or pending.get("name") not in {"develop", "finish"}
        or candidate is None
    ):
        raise ValueError("backtest action identity missing")
    return {
        "tool_call_id": pending["id"],
        "attempt_id": attempt_id,
        "name": pending["name"],
        "code_sha256": hashlib.sha256(candidate.strategy_code.encode()).hexdigest(),
    }


def reduce_checkpoint(projection: Any, payload: dict[str, Any]) -> None:
    entry = payload["entry"]
    if entry["action"] != action_identity(projection):
        raise ValueError("backtest action changed")
    if entry["request_hash"] != digest(entry["request"]):
        raise ValueError("backtest request changed")
    expected_key = digest([entry["action"]["tool_call_id"], entry["request"]["idempotency_key"]])
    if payload["key"] != expected_key:
        raise ValueError("backtest checkpoint key mismatch")
    entries = projection.avo.setdefault("backtest_effects", {})
    old = entries.get(expected_key)
    if old:
        if any(old[k] != entry[k] for k in ("action", "request_hash")):
            raise ValueError("backtest action/request receipt mismatch")
        if any(old.get(k) and old[k] != entry.get(k) for k in ("job_id", "input_snapshot_hash")):
            raise ValueError("backtest frozen job changed")
        if entry.get("resume_attempts", 0) < old.get("resume_attempts", 0):
            raise ValueError("backtest resume counter regressed")
    entries[expected_key] = dict(entry)


def recoverable(projection: Any, *, due: bool = True) -> bool:
    if projection.state == "needs_operator":
        reason = next(
            (
                e.payload.get("reason")
                for e in reversed(projection.events)
                if e.event_type == "operator_needed"
            ),
            None,
        )
        if reason != "avo_backtest_pending":
            return False
    try:
        identity = action_identity(projection)
    except ValueError:
        return False
    entries = [
        e
        for e in projection.avo.get("backtest_effects", {}).values()
        if e.get("action") == identity
    ]
    if not entries or any(e.get("phase") == "blocked" for e in entries):
        return False
    return not due or all(
        not e.get("next_check_at")
        or datetime.fromisoformat(e["next_check_at"]) <= datetime.now(UTC)
        for e in entries
    )


def bind_legacy_checkpoint(projection: Any, payload: dict[str, Any]) -> None:
    """Operator audit binds a pre-checkpoint job without charging its action again."""
    identity = action_identity(projection)
    charge = next(
        (e for e in projection.events if e.event_id == payload.get("charge_event_id")), None
    )
    requested = next(
        (
            e
            for e in reversed(projection.events)
            if e.event_type == "avo_tool_requested"
            and e.payload.get("id") == identity["tool_call_id"]
        ),
        None,
    )
    if (
        projection.state != "needs_operator"
        or identity["name"] != "develop"
        or charge is None
        or charge.event_type != "avo_development_requested"
        or charge.payload.get("attempt_id") != identity["attempt_id"]
        or requested is None
        or charge.timestamp < requested.timestamp
        or not payload.get("audit")
    ):
        raise ValueError("legacy backtest charge/audit does not match pending action")
    reduce_checkpoint(projection, payload)
    projection.avo.setdefault("recovered_phase_charges", {})[identity["tool_call_id"]] = (
        charge.event_type
    )
    projection.state = "validating"


class BacktestActionRunner:
    def __init__(self, controller: Any, check_owner: Any = None):
        self.controller = controller
        self.check_owner = check_owner

    def run(self, client: Any, **parameters: Any) -> dict[str, Any]:
        request = {
            k: v
            for k, v in parameters.items()
            if k not in {"wait_for_result", "timeout_sec", "poll_interval_sec"}
        }
        if not request.get("idempotency_key"):
            raise ValueError("durable backtest request key required")
        action = action_identity(self.controller.projection)
        key = digest([action["tool_call_id"], request["idempotency_key"]])
        stored = self.controller.projection.avo.get("backtest_effects", {}).get(key)
        entry = dict(
            stored
            or {
                "action": action,
                "request": request,
                "request_hash": digest(request),
                "phase": "planned",
                "resume_attempts": 0,
                "read_failures": 0,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        if entry["action"] != action:
            raise ValueError("backtest action mismatch")
        if entry["request_hash"] != digest(request):
            raise ValueError("backtest request mismatch")

        def save(**changes: Any) -> None:
            entry.update(changes)
            self.controller.apply_event(
                "avo_backtest_checkpoint", {"key": key, "entry": dict(entry)}
            )

        def defer(message: str, *, error: bool = False) -> NoReturn:
            failures = entry.get("read_failures", 0) + 1 if error else 0
            save(
                phase="blocked" if failures >= 5 else entry["phase"],
                read_failures=failures,
                next_check_at=(
                    datetime.now(UTC) + timedelta(seconds=min(300, 60 * max(1, failures)))
                ).isoformat(),
                last_error=message,
            )
            if failures >= 5:
                raise ValueError("backtest read recovery limit reached")
            raise BacktestDeferred(message)

        if not stored:
            save()
        if not entry.get("job_id"):
            if self.check_owner is not None:
                self.check_owner()
            try:
                created = client.backtest_start_job(**request, wait_for_result=False)
            except Exception as exc:
                defer(type(exc).__name__, error=True)
            job = created.get("job") or {}
            if not job.get("job_id") or not job.get("input_snapshot_hash"):
                save(phase="blocked")
                raise ValueError("backtest creation receipt missing frozen job identity")
            save(
                job_id=job["job_id"],
                input_snapshot_hash=job["input_snapshot_hash"],
                phase="submitted",
            )
        try:
            response = client.backtest_get_job(job_id=entry["job_id"])
        except Exception as exc:
            defer(type(exc).__name__, error=True)
        job = response.get("job") or {}
        if (
            job.get("job_id") != entry["job_id"]
            or job.get("input_snapshot_hash") != entry["input_snapshot_hash"]
            or str(job.get("strategy_id")) != str(request["strategy_id"])
        ):
            save(phase="blocked")
            raise ValueError("backtest frozen job identity mismatch")
        status = job.get("status")
        if status == "interrupted":
            if entry.get("phase") != "resume_requested" or entry.get("resume_from") != job.get(
                "updated_at"
            ):
                if entry["resume_attempts"] >= 2:
                    save(phase="blocked")
                    raise ValueError("backtest resume limit reached")
                save(
                    phase="resume_requested",
                    resume_attempts=entry["resume_attempts"] + 1,
                    resume_from=job.get("updated_at"),
                )
            try:
                if self.check_owner is not None:
                    self.check_owner()
                client.backtest_resume_job(
                    job_id=entry["job_id"],
                    idempotency_key=request["idempotency_key"]
                    + f"-resume-{entry['resume_attempts']}",
                )
            except Exception as exc:
                defer(type(exc).__name__, error=True)
            save(phase="waiting")
            defer("backtest resumed")
        if status in {"pending", "running", "cancelling"}:
            if datetime.now(UTC) - datetime.fromisoformat(entry["created_at"]) > timedelta(
                hours=24
            ):
                save(phase="blocked")
                raise ValueError("backtest wait limit reached; operator reconciliation required")
            save(phase="waiting")
            defer("backtest running")
        if status not in {"completed", "failed", "cancelled"}:
            save(phase="blocked")
            raise ValueError("unknown backtest state")
        save(phase="terminal", status=status, read_failures=0, next_check_at=None)
        return dict(response)
