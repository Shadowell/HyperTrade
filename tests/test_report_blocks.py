from __future__ import annotations

from io import StringIO

from hypertrade.agent.planner import ToolCallRecord
from hypertrade.cli import render_run
from hypertrade.reporting.blocks import (
    build_report_blocks_from_tool_calls,
    render_report_blocks,
)


def test_report_blocks_preserve_source_refs_and_missing_data() -> None:
    blocks = build_report_blocks_from_tool_calls(
        "Paper monitor reviewed.",
        [
            ToolCallRecord(
                tool_name="strategy_library_search",
                input_json={"query": "momentum"},
                output_json={
                    "source": "memory.strategy_knowledge",
                    "memory_count": 2,
                    "items": [
                        {
                            "strategy_key": "momentum_breakout_v1",
                            "evidence_count": 2,
                            "passed_count": 1,
                            "failed_count": 1,
                            "best": {
                                "memory_id": "mem_fast",
                                "experiment_id": "exp_fast",
                                "backtest_id": "bt_fast",
                                "variant_id": "fast",
                                "total_return_pct": "12.5",
                                "max_drawdown_pct": "3.1",
                                "trade_count": 8,
                                "score": "11.75",
                            },
                            "source_memory_ids": ["mem_slow", "mem_fast"],
                        }
                    ],
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_paper_dashboard",
                input_json={},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "dashboard": {
                        "system": {
                            "strategy_id": 105,
                            "strategy": "ETH paper monitor",
                            "state": "running",
                            "mode": "paper",
                        },
                        "equity": {"current": "101.5"},
                        "performance": {
                            "total_pnl_pct": "1.5",
                            "max_drawdown": "2.2",
                        },
                    },
                    "paper_scope": {"dashboard_scope": "current_dashboard"},
                    "monitor_summary": {
                        "mode": "read_only",
                        "data_gaps": ["missing per-strategy pnl"],
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "status": "success"},
                        {"tool": "bitpro_health", "status": "success"},
                        {"tool": "paper_dashboard", "status": "success"},
                    ],
                },
            ),
        ],
    )

    serialized = [block.to_dict() for block in blocks]
    assert {block["block_type"] for block in serialized} >= {
        "summary",
        "metric_table",
        "evidence_list",
        "missing_data",
        "audit_references",
    }
    assert all(
        {
            "block_type",
            "title",
            "source_refs",
            "metrics",
            "rows",
            "missing",
            "notes",
            "severity",
        }
        <= set(block)
        for block in serialized
    )

    source_ids = {source["source_id"] for block in serialized for source in block["source_refs"]}
    assert {"mem_fast", "strategy:105"} <= source_ids

    missing = {item for block in serialized for item in block["missing"]}
    assert "missing per-strategy pnl" in missing


def test_render_report_blocks_compact_hides_sources_and_audit_expands_them() -> None:
    blocks = build_report_blocks_from_tool_calls(
        "",
        [
            ToolCallRecord(
                tool_name="bitpro_paper_dashboard",
                input_json={},
                output_json={
                    "status": "ok",
                    "dashboard": {
                        "system": {"strategy_id": 105, "state": "running", "mode": "paper"},
                        "equity": {"current": "101.5"},
                        "performance": {"total_pnl_pct": "1.5", "max_drawdown": "2.2"},
                    },
                    "monitor_summary": {
                        "mode": "read_only",
                        "data_gaps": ["missing per-strategy pnl"],
                    },
                },
            )
        ],
    )

    compact = render_report_blocks(blocks, audit=False)
    assert "BitPro Paper Monitor" in compact
    assert "equity=101.5" in compact
    assert "missing per-strategy pnl" in compact
    assert "strategy:105" not in compact
    assert "bitpro.paper_dashboard" not in compact

    audit = render_report_blocks(blocks, audit=True)
    assert "Sources:" in audit
    assert "strategy:105" in audit
    assert "bitpro.paper_dashboard" in audit
    assert "bitpro_paper_dashboard" in audit


def test_cli_report_blocks_default_and_audit_modes(monkeypatch) -> None:
    report_blocks = [
        block.to_dict()
        for block in build_report_blocks_from_tool_calls(
            "",
            [
                ToolCallRecord(
                    tool_name="bitpro_paper_dashboard",
                    input_json={},
                    output_json={
                        "status": "ok",
                        "dashboard": {
                            "system": {
                                "strategy_id": 105,
                                "state": "running",
                                "mode": "paper",
                            },
                            "equity": {"current": "101.5"},
                            "performance": {
                                "total_pnl_pct": "1.5",
                                "max_drawdown": "2.2",
                            },
                        },
                        "monitor_summary": {
                            "mode": "read_only",
                            "data_gaps": ["missing per-strategy pnl"],
                        },
                    },
                )
            ],
        )
    ]
    run = {
        "id": "run_blocks",
        "status": "completed",
        "report_markdown": "# fallback should not render",
        "report_json": {"report_blocks": report_blocks},
        "trace_events": [],
    }

    default_output = StringIO()
    render_run(run, output=default_output)
    rendered_default = default_output.getvalue()
    assert "fallback should not render" in rendered_default
    assert "BitPro Paper Monitor" not in rendered_default
    assert "strategy:105" not in rendered_default

    monkeypatch.setenv("HYPERTRADE_REPORT_SOURCE", "audit")
    audit_output = StringIO()
    render_run(run, output=audit_output)
    rendered_audit = audit_output.getvalue()
    assert "Sources:" in rendered_audit
    assert "strategy:105" in rendered_audit
    assert "bitpro.paper_dashboard" in rendered_audit
