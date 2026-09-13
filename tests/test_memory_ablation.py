import importlib.util
import json

import pytest
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.store import reset_store
from hypertrade.providers.chat import ChatResponse, TokenUsage, ToolCallRequest
from test_evolution_memory import WINDOWS, record


def ablation():
    assert importlib.util.find_spec("hypertrade.evals.memory_ablation") is not None, (
        "missing durable paired evaluator"
    )
    from hypertrade.evals import memory_ablation

    return memory_ablation


def goal():
    return ARCGoalV1(
        objective="Research SOL trend",
        research_mode="avo",
        provider_name="codex",
        model_name="test-model",
        research_windows=WINDOWS,
        symbols=["SOL-USDT-SWAP"],
        paper_review_required=True,
        success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
        budget=ARCBudgetV1(max_candidates=2, max_model_calls=2, max_backtests=3),
    )


class StopProvider:
    name = "codex"
    model = "test-model"

    def __init__(self):
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append(messages)
        return ChatResponse(
            content="",
            tool_calls=[ToolCallRequest("stop", "stop", {"reason": "no evidence"})],
            usage=TokenUsage(input_tokens=10, output_tokens=2, reported=True),
        )


def test_pair_freezes_equal_controls_and_resumes_only_unfinished_arm(tmp_path):
    module = ablation()
    reset_store()
    manifest = module.create_pair(tmp_path, goal(), [record()])
    provider = StopProvider()
    module.run_pair(tmp_path, provider=provider, max_arms=1)
    assert len(provider.seen) == 1
    result = module.run_pair(tmp_path, provider=provider)
    assert len(provider.seen) == 2
    assert result["status"] == "complete"
    assert result["conclusion"] == "unknown"
    assert result["profitability_claim"] is False
    inputs = [json.loads(messages[1]["content"]) for messages in provider.seen]
    assert sorted(len(value["research_memory"]) for value in inputs) == [0, 1]
    for value in inputs:
        value.pop("research_memory")
    assert inputs[0] == inputs[1]
    assert result["difference"]["model_calls_used"] == 0
    assert result["difference"]["total_tokens"] == 0
    assert manifest["controls"]["budget"]["max_model_calls"] == 2
    module.run_pair(tmp_path, provider=provider)
    assert len(provider.seen) == 2


def test_pair_rejects_model_drift_before_spending_and_manifest_tampering(tmp_path):
    module = ablation()
    reset_store()
    module.create_pair(tmp_path, goal(), [record()])
    provider = StopProvider()
    provider.model = "other"
    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        module.run_pair(tmp_path, provider=provider)
    assert not provider.seen
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["controls"]["budget"]["max_model_calls"] = 99
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest_identity_mismatch"):
        module.run_pair(tmp_path, provider=StopProvider())


def test_pair_rejects_invalid_cost_target_before_creation(tmp_path):
    module = ablation()
    with pytest.raises(ValueError, match="invalid_cost_policy_hash"):
        module.create_pair(tmp_path, goal(), [record()], cost_policy_hash="claimed")
    assert not (tmp_path / "manifest.json").exists()


def test_pair_accepts_the_exact_versioned_memory_service_projection(tmp_path):
    module = ablation()
    from hypertrade.arc.evolution_memory import curate_memory

    projected, _ = curate_memory(
        [record()], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS
    )
    manifest = module.create_pair(tmp_path, goal(), projected)
    assert manifest["memory"] == projected
    assert manifest["selection"]["input_contract"] == "research_memory.v1"


def test_pair_rejects_tampered_versioned_memory(tmp_path):
    module = ablation()
    from hypertrade.arc.evolution_memory import curate_memory

    projected, _ = curate_memory(
        [record()], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS
    )
    projected[0]["contamination_reasons"] = ["final_holdout"]
    with pytest.raises(ValueError, match="invalid_research_memory"):
        module.create_pair(tmp_path, goal(), projected)


def test_pair_never_accepts_paper_authority_or_feedback_context(tmp_path):
    module = ablation()
    proposed = goal()
    proposed.feedback.enabled = True
    with pytest.raises(ValueError, match="isolated_research_only"):
        module.create_pair(tmp_path, proposed, [])


def test_pair_cannot_reuse_an_existing_research_namespace(tmp_path):
    module = ablation()
    proposed = goal()
    proposed.research_id = "existing-production-research"
    with pytest.raises(ValueError, match="isolated_research_only"):
        module.create_pair(tmp_path, proposed, [])


def test_pair_preserves_agent_review_mode_without_executing_review(tmp_path):
    module = ablation()
    proposed = goal()
    proposed.paper_review_mode = "agent"
    manifest = module.create_pair(tmp_path, proposed, [])
    assert manifest["controls"] == proposed.model_dump(mode="json")
    provider = StopProvider()
    module.run_pair(tmp_path, provider=provider)
    assert all(json.loads(m[1]["content"])["paper_review_mode"] == "agent" for m in provider.seen)


def test_result_cache_cannot_hide_or_reexecute_authoritative_arms(tmp_path):
    module = ablation()
    reset_store()
    module.create_pair(tmp_path, goal(), [record()])
    provider = StopProvider()
    module.run_pair(tmp_path, provider=provider, max_arms=1)
    (tmp_path / "result.json").write_text(json.dumps({"arms": {"on": {}, "off": {}}}))
    result = module.run_pair(tmp_path, provider=provider)
    assert len(provider.seen) == 2
    assert result["arms"]["on"]["model_calls_used"] == 1
    assert result["arms"]["off"]["model_calls_used"] == 1


def test_pair_rejects_order_tampering(tmp_path):
    module = ablation()
    module.create_pair(tmp_path, goal(), [])
    path = tmp_path / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["order"] = ["on", "on"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest_identity_mismatch"):
        module.run_pair(tmp_path, provider=StopProvider())


def test_interrupted_model_is_charged_and_resumes_in_a_new_process(tmp_path):
    import os
    import subprocess
    import sys

    module = ablation()
    reset_store()
    module.create_pair(tmp_path, goal(), [record()])

    class Interrupted(StopProvider):
        def chat(self, messages, tools=None):
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        module.run_pair(tmp_path, provider=Interrupted(), max_arms=1)
    script = """
import json, sys
from pathlib import Path
from hypertrade.evals.memory_ablation import run_pair
from test_memory_ablation import StopProvider
print(json.dumps(run_pair(Path(sys.argv[1]), provider=StopProvider())))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "backend/src:tests"},
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert sorted(a["model_calls_used"] for a in result["arms"].values()) == [1, 2]
    assert len((tmp_path / "requests.jsonl").read_text().splitlines()) == 3
    assert any(a["total_tokens"] is None for a in result["arms"].values())


def test_duplicate_measurement_uses_executed_evidence_for_both_arms():
    import hashlib

    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.evolution_memory import curate_memory

    module = ablation()
    reset_store()
    source = record(code_sha256=hashlib.sha256(b"code").hexdigest())
    source["development"]["code_sha256"] = source["code_sha256"]
    memory, _ = curate_memory([source], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS)
    ctrl = ARCController(goal=goal())
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": "a",
                "candidate_id": "c",
                "hypothesis": "repeat",
                "strategy_spec": source["spec"],
                "strategy_code": "code",
            }
        },
    )
    ctrl.projection.avo["development"] = {"a": source["development"]}
    assert module._summary(ctrl, memory)["repeated_experiments"] == 1
    reset_store()


class ResearchProvider(StopProvider):
    def chat(self, messages, tools=None):
        self.seen.append(messages)
        last = json.loads(messages[-1]["content"]) if messages[-1]["role"] == "tool" else {}
        if not last:
            name, args = (
                "propose",
                {
                    "hypothesis": "trend",
                    "family_key": "ma_crossover",
                    "direction": "long_only",
                    "parameter_bounds": {},
                },
            )
        elif "metrics" not in last:
            name, args = "develop", {"attempt_id": last["attempt_id"]}
        else:
            name, args = "finish", {"attempt_id": last["attempt_id"]}
        return ChatResponse(
            content="", tool_calls=[ToolCallRequest(str(len(messages)), name, args)]
        )


class ResearchExperiments:
    def __init__(self):
        self.calls = []

    def run(self, attempt, goal, *, purpose="final"):
        from hypertrade.arc.self_test import SelfTestResult

        assert goal.paper_authorization is None
        self.calls.append(purpose)
        return SelfTestResult(
            True,
            "validation",
            "123",
            f"bt-{len(self.calls)}",
            metrics={
                "net_return": 0.2,
                "cost_policy_hash": "c" * 64,
            },
        )


def test_both_arms_reach_validation_without_paper_effects(tmp_path):
    module = ablation()
    reset_store()
    proposed = goal()
    proposed.paper_review_mode = "agent"
    proposed.budget.max_model_calls = 4
    module.create_pair(tmp_path, proposed, [record()])
    provider, experiments = ResearchProvider(), ResearchExperiments()
    result = module.run_pair(tmp_path, provider=provider, experiments=experiments)
    assert experiments.calls == ["development", "final", "development", "final"]
    assert all(a["state"] == "paper_review_ready" for a in result["arms"].values())
    from hypertrade.db import ArcMission, Database
    from sqlalchemy import select

    with Database(f"sqlite:///{tmp_path / 'journal.db'}").session() as session:
        missions = session.scalars(select(ArcMission)).all()
        assert len(missions) == 2
        for mission in missions:
            assert all(
                a.get("paper_instance_id") is None for a in mission.projection_json["attempts"]
            )
            assert not any("approved" in e["event_type"] for e in mission.projection_json["events"])


def test_unknown_backtest_effect_is_never_replayed(tmp_path):
    module = ablation()
    reset_store()
    proposed = goal()
    proposed.budget.max_model_calls = 4
    module.create_pair(tmp_path, proposed, [])

    class Interrupted(ResearchExperiments):
        def run(self, attempt, goal, *, purpose="final"):
            self.calls.append(purpose)
            raise KeyboardInterrupt()

    unknown = Interrupted()
    with pytest.raises(KeyboardInterrupt):
        module.run_pair(tmp_path, provider=ResearchProvider(), experiments=unknown, max_arms=1)
    experiments = ResearchExperiments()
    result = module.run_pair(tmp_path, provider=ResearchProvider(), experiments=experiments)
    assert experiments.calls == ["development", "final"]
    assert any("pending_effect_or_model" in a["unknown"] for a in result["arms"].values())
