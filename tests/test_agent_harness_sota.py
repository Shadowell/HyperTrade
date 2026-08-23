"""
Unit & Integration Tests for SOTA Agent Harness Completion
"""

from hypertrade.agent.planner import ParallelToolPipeline


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
