import json
from dataclasses import replace

import pytest
from hypertrade.arc.avo import run_avo_research
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.self_test import SelfTestResult
from hypertrade.arc.store import reset_store, save_mission
from hypertrade.providers.chat import ChatResponse, ToolCallRequest


@pytest.fixture
def mission():
    reset_store()
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="研究趋势策略",
            paper_review_required=True,
            research_mode="avo",
            budget=ARCBudgetV1(max_candidates=2),
            success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
        )
    )
    save_mission(ctrl)
    yield ctrl
    reset_store()


class ScriptProvider:
    name = "fixture"
    model = "unit-test"

    def __init__(self):
        self.calls = 0
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append(json.loads(json.dumps(messages)))
        self.calls += 1
        last = json.loads(messages[-1]["content"]) if messages[-1]["role"] == "tool" else {}
        if self.calls in (1, 3):
            if self.calls == 3:
                assert last["metrics"]["net_return"] < 0
            name, args = (
                "propose",
                {
                    "hypothesis": "trend",
                    "family_key": "ma_crossover" if self.calls == 1 else "donchian_breakout",
                    "direction": "long_only",
                    "parameter_bounds": {},
                },
            )
        elif self.calls in (2, 4):
            name, args = "develop", {"attempt_id": last["attempt_id"]}
        else:
            name, args = "finish", {"attempt_id": last["attempt_id"]}
        return ChatResponse(content="", tool_calls=[ToolCallRequest(str(self.calls), name, args)])


class Experiments:
    def __init__(self):
        self.calls = []

    def run(self, attempt, goal, *, purpose="final"):
        self.calls.append(purpose)
        result = SelfTestResult(
            True,
            "val-final",
            "445",
            "bt-final" if purpose == "final" else f"bt-dev-{len(self.calls)}",
            metrics={"net_return": 0.2},
        )
        if len(self.calls) == 1:
            return replace(result, passed=False, metrics={"net_return": -0.1}, reasons=["loss"])
        return result


def test_agent_uses_development_feedback_and_final_result_is_not_fed_back(mission):
    provider, experiments = ScriptProvider(), Experiments()
    run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    assert experiments.calls == ["development", "development", "final"]
    assert provider.calls == 5
    assert mission.projection.state == "paper_review_ready"
    assert len(mission.projection.attempts) == 2
    assert all(a.paper_instance_id is None for a in mission.projection.attempts)
    assert "bt-final" not in json.dumps(provider.seen)
    assert mission.projection.goal.budget.model_calls_used == 5
    assert mission.projection.goal.budget.backtests_used == 3
    requests = {
        e.payload["request_hash"]
        for e in mission.projection.events
        if e.event_type == "avo_model_requested"
    }
    assert all(a.provider_request_hash in requests for a in mission.projection.attempts)
    assert [
        json.loads(messages[1]["content"])["budget"]["model_calls_used"]
        for messages in provider.seen
    ] == list(range(1, 6))


def test_pending_effect_on_restart_stops_without_reissuing(mission):
    mission.apply_event("avo_tool_requested", {"id": "lost", "name": "develop", "arguments": {}})
    provider = ScriptProvider()
    run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
    assert provider.calls == 0
    assert mission.projection.state == "needs_operator"
    assert mission.projection.events[-1].payload["reason"] == "avo_effect_unknown"


def test_model_budget_is_enforced_before_another_call(mission):
    mission.projection.goal.budget.max_model_calls = 1
    provider = ScriptProvider()
    experiments = Experiments()
    run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    assert provider.calls == 1
    assert experiments.calls == []
    assert mission.projection.state == "needs_operator"


def test_consumed_final_window_cannot_be_reused_for_more_research(mission):
    mission.apply_event("avo_final_requested", {"attempt_id": "x"})
    provider = ScriptProvider()
    run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
    assert provider.calls == 0
    assert mission.projection.events[-1].payload["reason"] == "avo_fresh_validation_window_required"


def test_concurrent_worker_cannot_issue_another_model_call(mission):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    mission.projection.goal.budget.max_model_calls = 1

    class Blocking(ScriptProvider):
        def chat(self, messages, tools=None):
            entered.set()
            assert release.wait(5)
            return super().chat(messages, tools)

    provider = Blocking()
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(
            run_avo_research, mission.mission_id, provider=provider, experiments=Experiments()
        )
        assert entered.wait(5)
        second = run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
        release.set()
        first.result(timeout=5)
    assert second["status"] == "busy"
    assert provider.calls == 1


def test_pending_dispatch_survives_database_reload(mission, tmp_path):
    from hypertrade.arc.store import configure_store, get_controller, reset_runtime
    from hypertrade.db import Database

    db = Database(f"sqlite:///{tmp_path}/avo.db")
    db.create_all()
    configure_store(db)
    save_mission(mission)
    mission.apply_event("avo_tool_requested", {"id": "pending", "name": "develop", "arguments": {}})
    reset_runtime()
    provider = ScriptProvider()
    run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
    assert provider.calls == 0
    restored = get_controller(mission.mission_id)
    assert restored.projection.avo["pending"]["id"] == "pending"
    assert restored.projection.state == "needs_operator"


def test_model_cannot_add_budget_or_execute_paper(mission):
    class Malicious:
        name = "fixture"
        model = "malicious-test"
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ChatResponse(
                    "", tool_calls=[ToolCallRequest("1", "paper_start", {"strategy_id": 1})]
                )
            if self.calls == 2:
                return ChatResponse(
                    "",
                    tool_calls=[
                        ToolCallRequest(
                            "2",
                            "propose",
                            {
                                "hypothesis": "bad",
                                "family_key": "ma_crossover",
                                "direction": "long_only",
                                "parameter_bounds": {},
                                "max_candidates": 999,
                            },
                        )
                    ],
                )
            return ChatResponse("I am finished")

    experiments = Experiments()
    run_avo_research(mission.mission_id, provider=Malicious(), experiments=experiments)
    assert experiments.calls == []
    assert mission.projection.attempts == []
    assert mission.projection.goal.budget.max_candidates == 2
    rejected = [e for e in mission.projection.events if e.event_type == "avo_tool_finished"]
    assert all(e.payload["result"]["status"] == "rejected" for e in rejected)


@pytest.mark.parametrize("crash_event", ["avo_tool_finished", "paper_review_requested"])
def test_acknowledged_experiment_is_recovered_without_rerun(mission, monkeypatch, crash_event):
    class Crash(BaseException):
        pass

    provider, experiments = ScriptProvider(), Experiments()
    original = mission.apply_event
    fired = False

    def interrupt(kind, payload):
        nonlocal fired
        if (
            not fired
            and kind == crash_event
            and (kind == "paper_review_requested" or payload.get("id") == "2")
        ):
            fired = True
            raise Crash()
        return original(kind, payload)

    monkeypatch.setattr(mission, "apply_event", interrupt)
    with pytest.raises(Crash):
        run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    monkeypatch.setattr(mission, "apply_event", original)
    run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    assert experiments.calls == ["development", "development", "final"]
    assert provider.calls == 5
    assert mission.projection.state == "paper_review_ready"
    assert mission.projection.avo["pending"] is None


def test_budget_extension_is_idempotent_and_cannot_change_on_retry(mission):
    payload = {
        "extra_candidates": 1,
        "extra_model_calls": 2,
        "operator_id": "op",
        "idempotency_key": "extension",
    }
    mission.apply_event("budget_extended", payload)
    mission.apply_event("budget_extended", dict(payload))
    assert mission.projection.goal.budget.max_candidates == 3
    assert mission.projection.goal.budget.max_model_calls == 22
    with pytest.raises(PermissionError):
        mission.apply_event("budget_extended", {**payload, "extra_candidates": 2})


def test_agent_can_end_without_fabricating_a_winner(mission):
    class Stop:
        name = "fixture"
        model = "stop-test"
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            return ChatResponse(
                "",
                tool_calls=[ToolCallRequest(str(self.calls), "stop", {"reason": "不足以支持假设"})],
            )

    mission.projection.goal.budget.max_model_calls = 2
    provider, experiments = Stop(), Experiments()
    run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    assert provider.calls == 1
    assert experiments.calls == []
    assert mission.projection.state == "needs_operator"
    assert any(e.payload.get("reason") == "avo_no_candidate" for e in mission.projection.events)


def test_unimplemented_validation_policy_is_not_silently_claimed(mission):
    mission.projection.goal.success_criteria.required_validation_policy = "validation_policy_v2"
    provider, experiments = ScriptProvider(), Experiments()
    run_avo_research(mission.mission_id, provider=provider, experiments=experiments)
    assert provider.calls == 0
    assert experiments.calls == []
    assert mission.projection.state == "needs_operator"


def test_inspecting_one_candidate_recovers_its_development_feedback(mission):
    class Inspect(ScriptProvider):
        def chat(self, messages, tools=None):
            if self.calls < 2:
                return super().chat(messages, tools)
            self.calls += 1
            last = json.loads(messages[-1]["content"])
            if self.calls == 3:
                return ChatResponse(
                    "",
                    tool_calls=[
                        ToolCallRequest(
                            "3",
                            "inspect",
                            {
                                "target": "candidate",
                                "attempt_id": last["attempt_id"],
                            },
                        )
                    ],
                )
            assert last["development"]["metrics"]["net_return"] == -0.1
            return ChatResponse(
                "", tool_calls=[ToolCallRequest("4", "stop", {"reason": "inspected"})]
            )

    provider = Inspect()
    run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
    assert provider.calls == 4
    assert any(e.payload.get("reason") == "avo_no_candidate" for e in mission.projection.events)


def test_provider_can_only_change_before_candidates_exist(mission):
    mission.apply_event("operator_needed", {"reason": "provider_unavailable"})
    mission.apply_event(
        "budget_extended",
        {
            "provider_name": "codex",
            "extra_candidates": 0,
            "operator_id": "op",
            "idempotency_key": "select-provider",
        },
    )
    assert mission.projection.goal.provider_name == "codex"
    mission.projection.goal.budget.max_model_calls = 1
    run_avo_research(mission.mission_id, provider=ScriptProvider(), experiments=Experiments())
    assert mission.projection.attempts
    with pytest.raises(PermissionError):
        mission.apply_event(
            "budget_extended",
            {
                "provider_name": "openai",
                "extra_candidates": 0,
                "operator_id": "op",
                "idempotency_key": "change-provider",
            },
        )


def test_switching_provider_discards_unexecuted_old_actions(mission):
    mission.projection.avo["awaiting"] = [{"id": "old-plan", "name": "propose", "arguments": {}}]
    mission.projection.avo["messages"] = []
    mission.apply_event("operator_needed", {"reason": "provider_unavailable"})
    mission.apply_event(
        "budget_extended",
        {
            "provider_name": "codex",
            "extra_candidates": 0,
            "operator_id": "op",
            "idempotency_key": "switch-old-plan",
        },
    )
    assert mission.projection.avo["awaiting"] == []
    assert "not_executed" in mission.projection.avo["messages"][-1]["content"]


def test_replayed_proposal_keeps_its_original_model_provenance(mission, monkeypatch):
    class Crash(BaseException):
        pass

    original = mission.apply_event

    def interrupt(kind, payload):
        if kind == "avo_tool_requested":
            raise Crash()
        return original(kind, payload)

    monkeypatch.setattr(mission, "apply_event", interrupt)
    with pytest.raises(Crash):
        run_avo_research(mission.mission_id, provider=ScriptProvider(), experiments=Experiments())
    monkeypatch.setattr(mission, "apply_event", original)

    class Updated:
        name = "fixture"
        model = "new-version"

        def chat(self, messages, tools=None):
            return ChatResponse(
                "", tool_calls=[ToolCallRequest("stop-new", "stop", {"reason": "done"})]
            )

    run_avo_research(mission.mission_id, provider=Updated(), experiments=Experiments())
    assert mission.projection.attempts[0].provider_model == "fixture:unit-test"


def test_task_model_selection_is_bound_and_cannot_change_after_proposal(mission):
    mission.apply_event("operator_needed", {"reason": "provider_unavailable"})
    payload = {
        "provider_name": "codex",
        "model_name": "gpt-6-astra",
        "operator_id": "op",
        "idempotency_key": "select-model",
    }
    mission.apply_event("budget_extended", payload)
    assert mission.projection.goal.model_name == "gpt-6-astra"
    with pytest.raises(PermissionError):
        mission.apply_event("budget_extended", {**payload, "model_name": "gpt-5.5"})
    run_avo_research(mission.mission_id, provider=ScriptProvider(), experiments=Experiments())
    with pytest.raises(PermissionError):
        mission.apply_event(
            "budget_extended", {**payload, "idempotency_key": "later", "model_name": "gpt-5.5"}
        )


def test_worker_resolves_task_model(mission, monkeypatch):
    mission.projection.goal.provider_name = "codex"
    mission.projection.goal.model_name = "gpt-6-astra"
    selected = {}

    def resolve(self, **kwargs):
        selected.update(kwargs)
        return ScriptProvider()

    monkeypatch.setattr("hypertrade.arc.avo.ProviderRuntime.get_chat_provider", resolve)
    run_avo_research(mission.mission_id, experiments=Experiments())
    assert selected == {"selected": "codex", "selected_model": "gpt-6-astra"}


def test_budget_context_reports_remaining_without_recounting_tool_history(mission):
    provider = ScriptProvider()
    run_avo_research(mission.mission_id, provider=provider, experiments=Experiments())
    contexts = [json.loads(messages[1]["content"]) for messages in provider.seen]
    assert [c["remaining"]["candidates"] for c in contexts] == [2, 1, 1, 0, 0]
    assert [c["budget"]["model_calls_used"] for c in contexts] == [1, 2, 3, 4, 5]
    assert contexts[2]["remaining"]["development_backtests"] == 8
    assert (
        contexts[2]["budget_semantics"]
        == "current_server_totals_including_history_and_this_model_request"
    )
    assert len(contexts[2]["candidate_ids"]) == 1
    # Request snapshots use exactly the same totals as the actual model input.
    events = [e for e in mission.projection.events if e.event_type == "avo_model_requested"]
    assert [e.payload["budget_snapshot"] for e in events] == [c["budget"] for c in contexts]


@pytest.mark.parametrize("expire_after_baseline", [False, True])
def test_feedback_candidate_gets_same_window_baseline_and_human_review(
    mission, expire_after_baseline
):
    from hypertrade.arc.adversarial import BlueTeamQuant

    baseline = BlueTeamQuant().propose_initial_strategy(
        "trend", "BTC-USDT-SWAP", family_key="ma_crossover", direction="long_only"
    )
    baseline.attempt_id = "baseline"
    mission.projection.goal.feedback_parent = {
        "mission_id": "parent",
        "instance_id": "source-paper",
        "evidence": {},
        "baseline": baseline.model_dump(mode="json"),
    }

    class Provider:
        name, model = "fixture", "unit"
        calls = 0

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                name, args = (
                    "propose",
                    {
                        "hypothesis": "longer trend",
                        "family_key": "ma_crossover",
                        "direction": "long_only",
                        "parameter_bounds": {
                            "fast_window": {"min": 16, "max": 16},
                            "slow_window": {"min": 64, "max": 64},
                        },
                    },
                )
            else:
                last = json.loads(messages[-1]["content"])
                name, args = (
                    ("develop" if self.calls == 2 else "finish"),
                    {"attempt_id": last["attempt_id"]},
                )
            return ChatResponse(
                content="", tool_calls=[ToolCallRequest(str(self.calls), name, args)]
            )

    class Compare:
        def __init__(self):
            self.calls = []

        def run(self, attempt, goal, *, purpose="final"):
            self.calls.append((attempt.attempt_id, purpose))
            if expire_after_baseline and attempt.attempt_id == "baseline":
                mission.projection.avo["started_at"] = "2000-01-01T00:00:00"
            return SelfTestResult(
                True,
                "validated",
                "strategy",
                f"bt-{len(self.calls)}",
                metrics={
                    "net_return": ".1" if attempt.attempt_id == "baseline" else ".2",
                    "max_drawdown": ".1",
                    "evaluation_window": {"purpose": purpose, "research_id": goal.research_id},
                },
            )

    experiments = Compare()
    run_avo_research(mission.mission_id, provider=Provider(), experiments=experiments)
    if expire_after_baseline:
        assert mission.projection.state == "needs_operator"
        assert len(experiments.calls) == 2
        assert mission.projection.avo["final_window_consumed"]
        assert not mission.projection.paper_review
        return
    assert mission.projection.state == "paper_review_ready"
    assert experiments.calls[1] == ("baseline", "final")
    assert len(experiments.calls) == 3
    assert mission.projection.goal.budget.backtests_used == 3
    assert (
        mission.projection.attempts[0].observed_metrics["baseline_comparison"]["backtest_id"]
        == "bt-2"
    )
    assert mission.projection.paper_review["feedback_parent"]["instance_id"] == "source-paper"
    assert mission.projection.attempts[0].paper_instance_id is None


def test_development_to_final_reuses_verified_platform_strategy(mission):
    from hypertrade.arc.self_test import ARCSelfTestService

    class Provider(ScriptProvider):
        def chat(self, messages, tools=None):
            if self.calls == 2:
                self.calls += 1
                return ChatResponse(
                    content="",
                    tool_calls=[
                        ToolCallRequest(
                            "3",
                            "finish",
                            {"attempt_id": json.loads(messages[-1]["content"])["attempt_id"]},
                        )
                    ],
                )
            return super().chat(messages, tools)

    class Platform:
        creates = reads = backtests = 0
        code = ""

        def strategy_validate_code(self, **kwargs):
            return {"status": "ok"}

        def strategy_create(self, **kwargs):
            self.creates += 1
            self.code = kwargs["script_content"]
            return {"strategy": {"id": 9}}

        def strategy_get(self, **kwargs):
            self.reads += 1
            return {"strategy": {"id": 9, "script_content": self.code}}

        def backtest_start_job(self, **kwargs):
            self.backtests += 1
            return {
                "backtest_result": {
                    "id": f"bt-{self.backtests}",
                    "metrics": {
                        "net_return": 0.12,
                        "sharpe": 2,
                        "max_drawdown": 0.05,
                        "trades": 40,
                    },
                }
            }

    platform = Platform()
    run_avo_research(
        mission.mission_id, provider=Provider(), experiments=ARCSelfTestService(platform)
    )
    assert (platform.creates, platform.reads, platform.backtests) == (1, 1, 2)
    assert mission.projection.state == "paper_review_ready"
