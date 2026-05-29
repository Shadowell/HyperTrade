"""Tests for the LLM-driven agent planner."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypertrade.agent.planner import AgentPlanner, PlannerResult
from hypertrade.providers.deepseek import ChatResponse, ToolCallRequest


def _fake_llm(*responses: ChatResponse) -> MagicMock:
    """Return a mock DeepSeekClient that replays `responses` in order."""
    llm = MagicMock()
    llm.chat.side_effect = list(responses)
    return llm


def _static_executor(results: dict[str, Any]) -> Any:
    """Return an executor that returns a fixed result per tool name."""

    def executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return dict(results.get(tool_name, {"ok": True}))

    return executor


class TestAgentPlannerSingleToolThenFinalAnswer:
    def test_calls_tool_and_returns_final_message(self) -> None:
        tool_call = ToolCallRequest(
            id="call_1", name="market_summary", arguments={}
        )
        first_response = ChatResponse(content="", tool_calls=[tool_call])
        final_response = ChatResponse(
            content="# Market Summary\n\nResearch output only. Not investment advice.",
            tool_calls=[],
        )

        llm = _fake_llm(first_response, final_response)
        executor = _static_executor({"market_summary": {"top_movers": []}})
        planner = AgentPlanner(llm)
        result: PlannerResult = planner.run("请做行情归纳", executor)

        assert result.final_message.startswith("# Market Summary")
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].tool_name == "market_summary"
        assert result.tool_calls[0].output_json == {"top_movers": []}
        assert llm.chat.call_count == 2


class TestAgentPlannerSpecificTickerTool:
    def test_can_call_specific_market_ticker_tool(self) -> None:
        tool_call = ToolCallRequest(
            id="call_eth",
            name="market_ticker",
            arguments={"symbol": "ETH"},
        )
        llm = _fake_llm(
            ChatResponse(content="", tool_calls=[tool_call]),
            ChatResponse(
                content="ETH checked. Research output only. Not investment advice.",
                tool_calls=[],
            ),
        )
        planner = AgentPlanner(llm)
        result = planner.run(
            "看下ETH行情",
            _static_executor(
                {
                    "market_ticker": {
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500",
                        "found": True,
                    }
                }
            ),
        )

        assert result.tool_calls[0].tool_name == "market_ticker"
        assert result.tool_calls[0].input_json == {"symbol": "ETH"}
        assert result.tool_calls[0].output_json["inst_id"] == "ETH-USDT-SWAP"


class TestAgentPlannerMultiTurnChain:
    def test_research_then_backtest_chain(self) -> None:
        research_call = ToolCallRequest(
            id="call_r", name="strategy_draft", arguments={"prompt": "BTC趋势突破"}
        )
        backtest_call = ToolCallRequest(
            id="call_b",
            name="backtest_run",
            arguments={"research_id": "srch_abc", "strategy_key": "momentum_breakout_v1"},
        )
        resp1 = ChatResponse(content="", tool_calls=[research_call])
        resp2 = ChatResponse(content="", tool_calls=[backtest_call])
        resp3 = ChatResponse(
            content="Backtest complete. Research output only. Not investment advice.",
            tool_calls=[],
        )

        llm = _fake_llm(resp1, resp2, resp3)
        executor = _static_executor(
            {
                "strategy_draft": {"id": "srch_abc", "strategy_key": "momentum_breakout_v1"},
                "backtest_run": {"id": "bt_xyz", "metrics": {"total_return_pct": "0.019"}},
            }
        )
        planner = AgentPlanner(llm)
        result = planner.run("研究BTC趋势突破并回测", executor)

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].tool_name == "strategy_draft"
        assert result.tool_calls[1].tool_name == "backtest_run"
        assert "Backtest complete" in result.final_message
        assert llm.chat.call_count == 3


class TestAgentPlannerNoToolCalls:
    def test_immediate_final_answer(self) -> None:
        immediate = ChatResponse(
            content="Hello, I am HyperTrade. Research output only. Not investment advice.",
            tool_calls=[],
        )
        llm = _fake_llm(immediate)
        planner = AgentPlanner(llm)
        result = planner.run("你好", _static_executor({}))

        assert result.final_message.startswith("Hello")
        assert result.tool_calls == []
        assert llm.chat.call_count == 1


class TestAgentPlannerMaxIterations:
    def test_stops_at_max_iterations(self) -> None:
        always_tool = ChatResponse(
            content="",
            tool_calls=[ToolCallRequest(id="x", name="market_summary", arguments={})],
        )
        llm = MagicMock()
        llm.chat.return_value = always_tool
        planner = AgentPlanner(llm)
        result = planner.run("loop", _static_executor({"market_summary": {}}))

        assert "max iterations" in result.final_message
        assert llm.chat.call_count == AgentPlanner.MAX_ITERATIONS
        assert len(result.tool_calls) == AgentPlanner.MAX_ITERATIONS


class TestAgentPlannerExecutorPassthrough:
    def test_executor_receives_correct_args(self) -> None:
        call = ToolCallRequest(
            id="call_rag",
            name="rag_search",
            arguments={"query": "funding rate risk", "limit": 5},
        )
        llm = _fake_llm(
            ChatResponse(content="", tool_calls=[call]),
            ChatResponse(
                content="Done. Research output only. Not investment advice.", tool_calls=[]
            ),
        )
        received: list[tuple[str, dict[str, Any]]] = []

        def tracking_executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
            received.append((tool_name, args))
            return {"hits": []}

        planner = AgentPlanner(llm)
        planner.run("rag query test", tracking_executor)

        assert received == [("rag_search", {"query": "funding rate risk", "limit": 5})]


class TestAgentPlannerDeepSeekReasoningContent:
    def test_preserves_reasoning_content_for_next_tool_turn(self) -> None:
        call = ToolCallRequest(id="call_market", name="market_summary", arguments={})
        llm = _fake_llm(
            ChatResponse(content="", reasoning_content="thinking tokens", tool_calls=[call]),
            ChatResponse(
                content="Done. Research output only. Not investment advice.",
                tool_calls=[],
            ),
        )
        planner = AgentPlanner(llm)

        planner.run("market", _static_executor({"market_summary": {"ok": True}}))

        second_messages = llm.chat.call_args_list[1].args[0]
        assistant_messages = [
            message for message in second_messages if message.get("role") == "assistant"
        ]
        assert assistant_messages[-1]["reasoning_content"] == "thinking tokens"
