"""
Unit & Integration Tests for SOTA Agent Harness Completion
"""

from hypertrade.agent.compactor import ContextCompactor
from hypertrade.agent.planner import ParallelToolPipeline


def test_context_compactor_pruning():
    compactor = ContextCompactor(
        max_turns_before_compaction=3,
        max_tool_payload_chars=50,
        protection_window_size=3,
    )

    data_payload = "X" * 200
    trace_events = [
        {"event_type": "goal_compiled", "payload": {"goal": "Optimize WTI Strategy"}},
        {"event_type": "tool_executed", "payload": {"tool_name": "candles", "data": data_payload}},
        {"event_type": "tool_executed", "payload": {"tool_name": "summary", "data": data_payload}},
        {"event_type": "candidate_validated", "payload": {"attempt_id": "att_val"}},
        {"event_type": "red_team_tested", "payload": {"metrics": data_payload}},
        {"event_type": "mission_completed", "payload": {}},
        {"event_type": "tool_executed", "payload": {"tool_name": "recent", "data": "recent"}},
    ]

    compacted, summary = compactor.compact_events(trace_events)

    assert summary.original_event_count == len(trace_events)
    assert summary.pruned_tool_payload_bytes > 0
    assert compacted[0]["payload"]["goal"] == "Optimize WTI Strategy"
    assert compacted[1].get("is_compacted") is True


def test_parallel_tool_pipeline_execution():
    call_log: list[str] = []

    def dummy_executor(name: str, args: dict) -> dict:
        call_log.append(name)
        return {"status": "ok", "tool": name, "result": args.get("val", 0) * 2}

    pipeline = ParallelToolPipeline(dummy_executor, max_workers=3)

    tool_calls = [
        {"name": "tool_a", "arguments": {"val": 10}},
        {"name": "tool_b", "arguments": {"val": 20}},
        {"name": "tool_c", "arguments": {"val": 30}},
    ]

    results = pipeline.execute_parallel_tools(tool_calls)

    assert len(results) == 3
    assert len(call_log) == 3
    assert results[0]["result"] == 20
    assert results[1]["result"] == 40
    assert results[2]["result"] == 60
