import pytest
from hypertrade.arc.backtest_recovery import BacktestActionRunner, BacktestDeferred
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.store import get_controller, reset_runtime, reset_store, save_mission


@pytest.fixture
def action():
    reset_store()
    c = ARCController(
        goal=ARCGoalV1(
            objective="recover",
            research_mode="avo",
            paper_review_required=True,
            success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
        )
    )
    c.projection.attempts.append(
        ARCCandidateAttemptV1(
            attempt_id="a", candidate_id="c", hypothesis="h", strategy_code="code", strategy_spec={}
        )
    )
    c.projection.avo = {
        "pending": {
            "kind": "tool",
            "name": "develop",
            "id": "call",
            "arguments": {"attempt_id": "a"},
        }
    }
    c.projection.state = "validating"
    save_mission(c)
    yield c
    reset_store()


class Jobs:
    def __init__(self):
        self.created = 0
        self.resumed = 0
        self.status = "running"
        self.disconnect = False

    def backtest_start_job(self, **kw):
        self.created += 1
        return {"job": {"job_id": "j", "input_snapshot_hash": "sha256:" + "a" * 64}}

    def backtest_get_job(self, **kw):
        if self.disconnect:
            raise ConnectionError("connection reset")
        return {
            "job": {
                "job_id": "j",
                "strategy_id": 7,
                "status": self.status,
                "input_snapshot_hash": "sha256:" + "a" * 64,
                "updated_at": "2026-10-15T00:00:00Z",
            },
            "backtest_result": {"id": "result", "metrics": {"net_return": 0.1}}
            if self.status == "completed"
            else None,
        }

    def backtest_resume_job(self, **kw):
        self.resumed += 1
        self.status = "running"
        return self.backtest_get_job(**kw)


REQUEST = {
    "strategy_id": 7,
    "start_date": "2026-01-01",
    "end_date": "2026-02-01",
    "initial_capital": 100,
    "idempotency_key": "experiment",
}


def test_restart_after_poll_disconnect_keeps_exact_job_and_resumes_only_interruption(action):
    client = Jobs()
    client.disconnect = True
    runner = BacktestActionRunner(action)
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)
    assert client.created == 1
    reset_runtime()
    restored = get_controller(action.mission_id)
    client.disconnect = False
    client.status = "interrupted"
    with pytest.raises(BacktestDeferred):
        BacktestActionRunner(restored).run(client, **REQUEST)
    assert client.created == 1 and client.resumed == 1
    client.status = "completed"
    result = BacktestActionRunner(restored).run(client, **REQUEST)
    assert result["job"]["job_id"] == "j"
    assert client.created == 1 and client.resumed == 1


def test_changed_request_or_source_never_reuses_old_receipt(action):
    runner = BacktestActionRunner(action)
    client = Jobs()
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)
    with pytest.raises(ValueError, match="request"):
        runner.run(client, **{**REQUEST, "initial_capital": 200})
    action.projection.attempts[0].strategy_code = "different"
    with pytest.raises(ValueError, match="action"):
        runner.run(client, **REQUEST)
    assert client.created == 1


def test_failed_or_cancelled_job_is_never_automatically_resumed(action):
    client = Jobs()
    client.status = "failed"
    result = BacktestActionRunner(action).run(client, **REQUEST)
    assert result["job"]["status"] == "failed"
    assert client.resumed == 0


def test_resume_attempts_are_bounded(action):
    client = Jobs()
    runner = BacktestActionRunner(action)
    for _ in range(2):
        client.status = "interrupted"
        with pytest.raises(BacktestDeferred):
            runner.run(client, **REQUEST)
    client.status = "interrupted"
    with pytest.raises(ValueError, match="resume limit"):
        runner.run(client, **REQUEST)
    assert client.resumed == 2


def test_worker_recovers_without_recharging_tool_or_backtest_budget(action):
    from hypertrade.arc.avo import ResearchStopped, _perform, needs_research, run_avo_research
    from hypertrade.arc.self_test import SelfTestResult

    class Experiment:
        def __init__(self, controller, client):
            self.runner = BacktestActionRunner(controller)
            self.client = client

        def run(self, candidate, goal, **kwargs):
            r = self.runner.run(self.client, **REQUEST)
            return SelfTestResult(False, None, "7", r["job"]["job_id"], reasons=["quality_failed"])

    client = Jobs()
    with pytest.raises(ResearchStopped, match="avo_backtest_pending"):
        _perform(action, "develop", {"attempt_id": "a"}, Experiment(action, client))
    action.apply_event("operator_needed", {"reason": "avo_backtest_pending"})
    used = action.projection.goal.budget.backtests_used
    assert used == 1 and not needs_research(action.projection)
    for key, entry in list(action.projection.avo["backtest_effects"].items()):
        action.apply_event(
            "avo_backtest_checkpoint", {"key": key, "entry": {**entry, "next_check_at": None}}
        )
    reset_runtime()
    restored = get_controller(action.mission_id)
    assert needs_research(restored.projection)
    client.status = "completed"
    run_avo_research(restored.mission_id, experiments=Experiment(restored, client))
    assert restored.projection.avo["pending"] is None
    assert restored.projection.goal.budget.backtests_used == used
    assert client.created == 1
    assert restored.projection.avo["development"]["a"]["passed"] is False


def test_running_job_cannot_wait_forever_or_be_replaced(action, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import hypertrade.arc.backtest_recovery as recovery

    client = Jobs()
    runner = BacktestActionRunner(action)
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(hours=25)

    monkeypatch.setattr(recovery, "datetime", Later)
    with pytest.raises(ValueError, match="wait limit"):
        runner.run(client, **REQUEST)
    assert client.created == 1 and client.resumed == 0
    assert not recovery.recoverable(action.projection)


def test_operator_stop_is_not_overridden_by_a_recoverable_job(action):
    from hypertrade.arc.backtest_recovery import recoverable

    client = Jobs()
    with pytest.raises(BacktestDeferred):
        BacktestActionRunner(action).run(client, **REQUEST)
    action.apply_event("operator_needed", {"reason": "operator_paused"})
    assert not recoverable(action.projection, due=False)


def test_unclassified_error_is_not_retried_just_because_an_old_checkpoint_exists(action):
    from hypertrade.arc.backtest_recovery import recoverable

    with pytest.raises(BacktestDeferred):
        BacktestActionRunner(action).run(Jobs(), **REQUEST)
    action.apply_event("operator_needed", {"reason": "avo_effect_unknown"})
    assert not recoverable(action.projection, due=False)


def test_runtime_change_creates_explicit_successor_without_overwriting_old_job(action):
    from hypertrade.bitpro.mcp import BitProMcpError

    class ChangedRuntime(Jobs):
        def __init__(self):
            super().__init__()
            self.done = False
            self.started = []

        def backtest_start_job(self, **kw):
            self.started.append(kw)
            self.created += 1
            return {
                "job": {
                    "job_id": "new" if kw.get("recovery_of_job_id") else "old",
                    "input_snapshot_hash": "sha256:"
                    + ("b" if kw.get("recovery_of_job_id") else "a") * 64,
                    "recovery_of_job_id": kw.get("recovery_of_job_id"),
                }
            }

        def backtest_get_job(self, job_id):
            return {
                "job": {
                    "job_id": job_id,
                    "strategy_id": 7,
                    "status": ("completed" if self.done else "running")
                    if job_id == "new"
                    else "interrupted",
                    "input_snapshot_hash": "sha256:" + ("b" if job_id == "new" else "a") * 64,
                    "updated_at": "2026-10-15T00:00:00Z",
                }
            }

        def backtest_resume_job(self, **kw):
            raise BitProMcpError("backtest_source_or_deployment_changed", status_code=409)

    client = ChangedRuntime()
    runner = BacktestActionRunner(action)
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)
    assert client.created == 2
    assert client.started[-1]["recovery_of_job_id"] == "old"
    entries = list(action.projection.avo["backtest_effects"].values())
    assert {e.get("job_id") for e in entries} == {"old", "new"}
    assert next(e for e in entries if e["job_id"] == "old")["phase"] == "superseded"
    client.done = True
    assert runner.run(client, **REQUEST)["job"]["job_id"] == "new"


def test_corrupt_snapshot_rejection_does_not_create_successor(action):
    from hypertrade.bitpro.mcp import BitProMcpError

    class Corrupt(Jobs):
        def backtest_resume_job(self, **kw):
            raise BitProMcpError("backtest_input_hash_mismatch", status_code=409)

    c = Corrupt()
    c.status = "interrupted"
    with pytest.raises(ValueError, match="rejected"):
        BacktestActionRunner(action).run(c, **REQUEST)
    assert c.created == 1


def test_invalid_revalidation_event_cannot_partially_change_old_checkpoint(action):
    from copy import deepcopy

    from hypertrade.arc.backtest_recovery import digest

    client = Jobs()
    runner = BacktestActionRunner(action)
    with pytest.raises(BacktestDeferred):
        runner.run(client, **REQUEST)
    key, entry = next(iter(action.projection.avo["backtest_effects"].items()))
    action.apply_event(
        "avo_backtest_checkpoint",
        {"key": key, "entry": {**entry, "phase": "resume_requested", "resume_attempts": 1}},
    )
    entry = action.projection.avo["backtest_effects"][key]
    before = deepcopy(action.projection.avo["backtest_effects"])
    request = {
        **entry["request"],
        "idempotency_key": "version",
        "recovery_of_job_id": entry["job_id"],
    }
    invalid = {
        "action": entry["action"],
        "request": request,
        "request_hash": "wrong",
        "resume_attempts": 1,
        "revision": 1,
        "phase": "planned",
    }
    with pytest.raises(ValueError):
        action.apply_event(
            "avo_backtest_revalidation",
            {
                "previous_key": key,
                "key": digest(["call", "version"]),
                "entry": invalid,
                "reason": "backtest_source_or_deployment_changed",
            },
        )
    assert action.projection.avo["backtest_effects"] == before


def test_legacy_charge_binding_requires_original_requested_action(action):
    from hypertrade.arc.backtest_recovery import action_identity, digest

    pending = dict(action.projection.avo["pending"])
    action.apply_event("avo_tool_requested", {k: v for k, v in pending.items() if k != "kind"})
    charge = action.apply_event("avo_development_requested", {"attempt_id": "a"})
    action.apply_event("operator_needed", {"reason": "avo_effect_unknown"})
    identity = action_identity(action.projection)
    entry = {
        "action": identity,
        "request": REQUEST,
        "request_hash": digest(REQUEST),
        "phase": "submitted",
        "job_id": "j",
        "input_snapshot_hash": "sha256:" + "a" * 64,
    }
    payload = {
        "key": digest(["call", REQUEST["idempotency_key"]]),
        "entry": entry,
        "charge_event_id": charge.event_id,
        "audit": {"job_verified": True},
    }
    action.apply_event("avo_backtest_recovery_bound", payload)
    assert action.projection.goal.budget.backtests_used == 1
    assert action.projection.avo["recovered_phase_charges"]["call"] == "avo_development_requested"
    with pytest.raises(ValueError, match="charge/audit"):
        action.apply_event("avo_backtest_recovery_bound", {**payload, "charge_event_id": "other"})


def test_final_two_legs_recover_with_exactly_two_budget_charges(action):
    from datetime import UTC, datetime

    from hypertrade.arc.avo import ResearchStopped, _perform, run_avo_research
    from hypertrade.arc.self_test import SelfTestResult

    baseline = action.projection.attempts[0].model_copy(
        update={"attempt_id": "baseline_source", "candidate_id": "base"}
    )
    action.projection.goal.evolution_context = {"baseline": baseline.model_dump(mode="json")}
    action.projection.avo["started_at"] = datetime.now(UTC).isoformat()
    action.projection.avo["pending"]["name"] = "finish"
    action.projection.avo["development"] = {"a": {"passed": True, "bitpro_strategy_id": "7"}}
    save_mission(action)

    class BothJobs(Jobs):
        def __init__(self):
            super().__init__()
            self.requests = {}
            self.done = set()

        def backtest_start_job(self, **kw):
            self.created += 1
            key = kw["idempotency_key"]
            self.requests[key] = kw
            return {"job": {"job_id": key, "input_snapshot_hash": "sha256:" + "a" * 64}}

        def backtest_get_job(self, job_id):
            return {
                "job": {
                    "job_id": job_id,
                    "strategy_id": self.requests[job_id]["strategy_id"],
                    "status": "completed" if job_id in self.done else "running",
                    "input_snapshot_hash": "sha256:" + "a" * 64,
                }
            }

    client = BothJobs()

    class Experiment:
        def run(self, candidate, goal, **kw):
            base = candidate.attempt_id.startswith("baseline_")
            key = "baseline" if base else "candidate"
            result = BacktestActionRunner(action).run(
                client, **{**REQUEST, "strategy_id": 8 if base else 7, "idempotency_key": key}
            )
            return SelfTestResult(
                False,
                None,
                str(8 if base else 7),
                result["job"]["job_id"],
                metrics={
                    "evaluation_window": {"purpose": "final"},
                    "net_return": 0,
                    "max_drawdown": 0.1,
                },
            )

    with pytest.raises(ResearchStopped, match="avo_backtest_pending"):
        _perform(action, "finish", {"attempt_id": "a"}, Experiment())
    assert action.projection.goal.budget.backtests_used == 1

    def advance(key):
        client.done.add(key)
        action.apply_event("operator_needed", {"reason": "avo_backtest_pending"})
        for k, e in list(action.projection.avo["backtest_effects"].items()):
            action.apply_event(
                "avo_backtest_checkpoint", {"key": k, "entry": {**e, "next_check_at": None}}
            )
        run_avo_research(action.mission_id, experiments=Experiment())

    advance("baseline")
    assert action.projection.goal.budget.backtests_used == 2
    advance("candidate")
    assert action.projection.goal.budget.backtests_used == 2
    assert action.projection.avo["pending"] is None
    assert client.created == 2
