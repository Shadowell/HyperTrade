from copy import deepcopy

from hypertrade.arc.evolution_memory import curate_memory
from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from test_evolution_memory import WINDOWS, record


def test_avo_projects_versioned_identity_without_backfilling_unknown_config():
    source = record()
    source["development"]["metrics"].pop("config_sha256", None)
    before = deepcopy(source)
    entries, _ = curate_memory([source], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS)
    assert entries[0].get("schema_version") == "research_memory.v1"
    assert entries[0]["config_sha256"] is None
    assert entries[0]["identity_status"] == "unknown"
    assert entries[0]["exclusion_reasons"] == ["missing_config_identity"]
    assert entries[0]["approval_allowed"] is False
    from hypertrade.memory.research import ResearchMemoryV1

    assert ResearchMemoryV1.model_validate(entries[0]).mission_id == "source"
    assert source == before


def test_research_memory_canonicalizes_equivalent_capital_identity():
    source = record(capital="100.0")
    entries, _ = curate_memory(
        [source], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS
    )
    assert entries[0]["capital"] == "100"


def test_shared_projection_checks_cost_and_persistent_invalidation(tmp_path):
    url = f"sqlite:///{tmp_path / 'memory.db'}"
    db = Database(url)
    db.create_all()
    source = record()
    source["development"]["metrics"]["config_sha256"] = "d" * 64
    service = MemoryService(db)
    args = {"symbol": "SOL-USDT-SWAP", "timeframe": "1H", "windows": WINDOWS}
    assert hasattr(service, "project_research"), "MemoryService needs the shared research contract"
    entries, _ = service.project_research([source], **args, cost_policy_hash="c" * 64)
    assert len(entries) == 1
    assert entries[0]["identity_status"] == "known"
    rejected, manifest = service.project_research([source], **args, cost_policy_hash="e" * 64)
    assert rejected == []
    assert manifest["excluded"]["cost_identity_mismatch"] == 1
    service.invalidate_research(
        mission_id="source", backtest_id="receipt", reason="holdout_contamination", actor="test"
    )
    db.engine.dispose()
    restarted = MemoryService(Database(url))
    rejected, manifest = restarted.project_research([source], **args)
    assert rejected == []
    assert manifest["excluded"]["invalidated"] == 1
    assert source["development"]["passed"] is False


def test_unknown_source_and_declared_contamination_are_not_recalled():
    sources = [record(mission_id=""), record(contamination_reasons=["final_holdout"])]
    entries, manifest = curate_memory(
        sources, symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS
    )
    assert entries == []
    assert manifest["excluded"] == {"unknown_source": 1, "contaminated": 1}


def test_unknown_config_identity_cannot_support_a_direction_assessment():
    from hypertrade.arc.evolution_memory import assess_hypothesis

    source = record()
    source["development"]["metrics"].pop("config_sha256", None)
    entries, _ = curate_memory([source], symbol="SOL-USDT-SWAP", timeframe="1H", windows=WINDOWS)
    spec = {
        **source["spec"],
        "evolution_hypothesis": {
            "evidence_refs": [entries[0]["memory_id"]],
            "expected_metric": "net_return",
            "expected_direction": "increase",
        },
    }
    assessment = assess_hypothesis(
        spec, {**source["development"]["metrics"], "net_return": 0.9}, entries, WINDOWS, "100"
    )
    assert assessment["status"] == "unknown"
    assert assessment["comparisons"] == []


def test_general_memory_reads_authoritative_arc_receipts_after_process_restart(tmp_path):
    import json
    import os
    import subprocess
    import sys

    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.store import configure_store, reset_store, save_mission

    url = f"sqlite:///{tmp_path / 'source.db'}"
    db = Database(url)
    db.create_all()
    reset_store()
    configure_store(db)
    source = record()
    ctrl = ARCController(goal=ARCGoalV1(objective="trend", symbols=["SOL-USDT-SWAP"]))
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": {
                "attempt_id": "a",
                "candidate_id": "c",
                "hypothesis": "churn",
                "strategy_spec": source["spec"],
                "strategy_code": "source code",
            }
        },
    )
    import hashlib

    source["development"]["code_sha256"] = hashlib.sha256(b"source code").hexdigest()
    ctrl.projection.avo["development"] = {"a": source["development"]}
    save_mission(ctrl)
    reset_store()
    script = """
import json, sys
from datetime import date
from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from hypertrade.arc.contracts import ResearchWindowsV1
s = MemoryService(Database(sys.argv[1]))
assert hasattr(s, 'research_context'), 'missing source-bound recall'
entries, manifest = s.research_context(symbol='SOL-USDT-SWAP', timeframe='1H',
    windows=ResearchWindowsV1(as_of=date(2026,9,12)))
print(json.dumps(entries))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, url],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "backend/src"},
    )
    assert result.returncode == 0, result.stderr
    entries = json.loads(result.stdout)
    assert entries[0]["development"]["backtest_id"] == "receipt"
    assert entries[0]["mission_id"] == ctrl.mission_id
