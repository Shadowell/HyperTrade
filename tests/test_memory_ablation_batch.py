import json
import os
import subprocess
import sys

import pytest
from hypertrade.arc.store import reset_store
from test_memory_ablation import StopProvider, goal


def tasks():
    first, second = goal(), goal()
    second.objective = "Research another SOL trend hypothesis"
    return [
        {"task_id": "sol-breakout", "goal": first, "records": []},
        {"task_id": "sol-pullback", "goal": second, "records": []},
    ]


def test_batch_freezes_controls_and_rejects_drift_before_dispatch(tmp_path):
    from hypertrade.evals.memory_ablation_batch import create_batch, run_batch

    manifest = create_batch(tmp_path, tasks())
    assert len(manifest["tasks"]) == 2
    assert len({item["pair_id"] for item in manifest["tasks"]}) == 2
    assert all(
        (tmp_path / "pairs" / item["task_id"] / "manifest.json").exists()
        for item in manifest["tasks"]
    )
    drifted = tasks()
    drifted[1]["goal"].budget.max_model_calls += 1
    with pytest.raises(ValueError, match="batch_control_mismatch"):
        create_batch(tmp_path / "other", drifted)
    with pytest.raises(ValueError, match="duplicate_task_id"):
        create_batch(tmp_path / "duplicate", [tasks()[0], tasks()[0]])
    assert create_batch(tmp_path, tasks()) == manifest
    changed_input = tasks()
    changed_input[0]["goal"].objective = "Changed objective"
    with pytest.raises(ValueError, match="pair_directory_already_bound"):
        create_batch(tmp_path, changed_input)
    changed = json.loads((tmp_path / "batch_manifest.json").read_text())
    changed["tasks"][0]["pair_id"] = "0" * 64
    (tmp_path / "batch_manifest.json").write_text(json.dumps(changed))
    reset_store()
    with pytest.raises(ValueError, match="batch_manifest_identity_mismatch"):
        run_batch(tmp_path, provider=StopProvider())


def test_batch_resumes_across_process_and_rebuilds_aggregate_from_journals(tmp_path):
    from hypertrade.evals.memory_ablation_batch import create_batch, run_batch

    reset_store()
    create_batch(tmp_path, tasks())
    first_provider = StopProvider()
    pending = run_batch(tmp_path, provider=first_provider, max_pairs=1)
    assert pending["status"] == "pending"
    assert pending["metrics"]["on"]["success_rate"] is None
    assert len(first_provider.seen) == 2
    (tmp_path / "batch_result.json").write_text('{"status":"complete","conclusion":"effective"}')
    script = """
import json, sys
from pathlib import Path
from hypertrade.evals.memory_ablation_batch import run_batch
from test_memory_ablation import StopProvider
p = StopProvider()
r = run_batch(Path(sys.argv[1]), provider=p)
print(json.dumps({'result': r, 'calls': len(p.seen)}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "backend/src:tests"},
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    result = payload["result"]
    assert payload["calls"] == 2
    assert result["status"] == "complete"
    assert result["conclusion"] == "unknown"
    assert result["profitability_claim"] is False
    assert result["causal_claim"] is False
    assert result["metrics"]["on"]["model_calls_used"] == 2
    assert result["metrics"]["off"]["tool_calls_used"] == 2
    assert result["metrics"]["on"]["success_rate"] == 0
    assert result["metrics"]["on"]["repeat_rate"] is None
    assert result["metrics"]["on"]["failure_classes"]["avo_no_candidate"] == 2
    assert result["paired_outcomes"] == {
        "improved": 0,
        "regressed": 0,
        "unchanged": 2,
        "unknown": 0,
    }
    assert "no_validated_candidate" in result["unknown"]
    assert "single_pair_not_effectiveness_evidence" not in result["unknown"]
    assert run_batch(tmp_path, provider=StopProvider()) == result


def test_batch_keeps_missing_usage_and_zero_experiment_rate_unknown(tmp_path):
    from hypertrade.evals.memory_ablation_batch import create_batch, run_batch

    class UnknownUsage(StopProvider):
        def chat(self, messages, tools=None):
            response = super().chat(messages, tools)
            response.usage.reported = False
            return response

    reset_store()
    create_batch(tmp_path, tasks())
    result = run_batch(tmp_path, provider=UnknownUsage())
    assert result["metrics"]["on"]["total_tokens"] is None
    assert result["metrics"]["on"]["repeat_rate"] is None
    assert "provider_usage_unreported" in result["unknown"]


def test_batch_rejects_paper_authority_and_unsafe_task_id(tmp_path):
    from hypertrade.evals.memory_ablation_batch import create_batch

    selected = tasks()
    selected[0]["task_id"] = "../escape"
    with pytest.raises(ValueError, match="invalid_task_id"):
        create_batch(tmp_path, selected)
    selected = tasks()
    selected[0]["goal"].feedback.enabled = True
    selected[1]["goal"].feedback.enabled = True
    with pytest.raises(ValueError, match="isolated_research_only"):
        create_batch(tmp_path, selected)


def test_batch_status_rebuild_never_resolves_or_calls_a_provider(tmp_path, monkeypatch):
    from hypertrade.evals.memory_ablation_batch import create_batch, run_batch

    reset_store()
    create_batch(tmp_path, tasks())
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider_resolved")),
    )
    result = run_batch(tmp_path, max_pairs=0)
    assert result["status"] == "pending"
    assert result["paired_outcomes"]["unknown"] == 2


def test_batch_rejects_aggregation_runtime_drift(tmp_path, monkeypatch):
    from hypertrade.evals import memory_ablation_batch as batch

    batch.create_batch(tmp_path, tasks())
    monkeypatch.setattr(batch, "_batch_runtime_digest", lambda: "changed-runtime")
    with pytest.raises(ValueError, match="batch_runtime_identity_mismatch"):
        batch.run_batch(tmp_path, provider=StopProvider(), max_pairs=0)


def test_batch_repeat_rate_uses_development_experiments_not_final_backtests():
    from hypertrade.evals.memory_ablation_batch import _aggregate

    arm = {
        "state": "paper_review_ready",
        "failure_reasons": [],
        "unknown": [],
        "model_calls_used": 3,
        "tool_calls_used": 2,
        "backtests_used": 4,
        "candidates_used": 2,
        "total_tokens": 100,
        "development_experiments": 2,
        "repeated_experiments": 1,
    }
    pair = {"status": "complete", "arms": {"on": arm, "off": arm}, "unknown": []}
    manifest = {"batch_id": "batch", "tasks": [{"task_id": "a"}, {"task_id": "b"}]}
    result = _aggregate(manifest, {"a": pair, "b": pair})
    assert result["metrics"]["on"]["repeat_rate"] == 0.5
    assert result["metrics"]["on"]["success_rate"] == 1
    assert result["metrics"]["on"]["backtests_used"] == 8


def test_batch_classifies_cross_task_regression_without_effectiveness_claim():
    from hypertrade.evals.memory_ablation_batch import _aggregate

    failed = {
        "state": "needs_operator",
        "failure_reasons": ["development_failed"],
        "unknown": ["no_validated_candidate"],
        "model_calls_used": 1,
        "tool_calls_used": 1,
        "backtests_used": 1,
        "candidates_used": 1,
        "total_tokens": 10,
        "development_experiments": 1,
        "repeated_experiments": 0,
    }
    passed = {**failed, "state": "paper_review_ready", "failure_reasons": [], "unknown": []}
    pair = {"status": "complete", "arms": {"on": failed, "off": passed}, "unknown": []}
    manifest = {"batch_id": "batch", "tasks": [{"task_id": "a"}, {"task_id": "b"}]}
    result = _aggregate(manifest, {"a": pair, "b": pair})
    assert result["paired_outcomes"]["regressed"] == 2
    assert result["paired_outcomes"]["improved"] == 0
    assert result["conclusion"] == "unknown"
