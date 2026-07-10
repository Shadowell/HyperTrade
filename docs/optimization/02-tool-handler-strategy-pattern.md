# 优化计划 2：Agent 工具派发 if/elif → 策略模式

## 现状诊断

`backend/src/hypertrade/agent/kernel.py:352-675` 是一个 ~350 行的巨型 `if/elif` 链：

```python
if tool_name == "market_summary":
    raw = self._market_summary(...)
elif tool_name == "market_ticker":
    raw = self._market_ticker(...)
elif tool_name == "market_candles":
    raw = self._fetch_market_candles(...)
# ... 40+ branches ...
elif tool_name.startswith("bitpro_"):
    raw = self._dispatch_bitpro_tool(...)
```

每个分支重复相同的模式：调用 handler → 构建 payload → attach metadata。违反 OCP（开闭原则）。

另外 `kernel.py:1238-2231`（~1000 行）的 `_render_planner_report()` 也是一个巨型 switch，遍历 tool call records 并按工具名分支生成报告段落。

## 目标

引入 `ToolHandler` 协议 + 注册机制，让每个工具成为独立的 handler 类。
Kernel 只负责通用编排（governance → execute → emit → report），工具特定逻辑全部委托给 handler。

## 涉及文件

| 操作 | 文件 |
|------|------|
| 新建 | `backend/src/hypertrade/tools/handler_protocol.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/__init__.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/market.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/rag.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/memory.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/strategy.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/backtest.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/bitpro.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/live.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/world_model.py` |
| 新建 | `backend/src/hypertrade/tools/handlers/global_market.py` |
| 改造 | `backend/src/hypertrade/agent/kernel.py` |
| 改造 | `backend/src/hypertrade/main.py` |
| 改造 | `tests/test_agent_acceptance.py` |

---

## 核心设计

### handler_protocol.py（新建）

```python
"""Tool handler protocol and registry for the Agent kernel."""
from dataclasses import dataclass, field
from typing import Protocol, Any


@dataclass
class ToolResult:
    """Result of a tool execution, consumed by AgentKernel."""
    payload: dict[str, Any] | None = None
    report: str | None = None
    report_attach_to: str = "this"  # "this" | "next" | "final"
    error: str | None = None

    @classmethod
    def ok(cls, payload: dict[str, Any] | None = None,
           report: str | None = None, report_attach_to: str = "this") -> "ToolResult":
        return cls(payload=payload, report=report, report_attach_to=report_attach_to)

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(error=error)


class ToolHandler(Protocol):
    """Protocol for tool execution handlers.

    Each tool handler is responsible for:
    1. executing the tool logic
    2. rendering its section in the final agent report
    """

    tool_name: str

    def execute(self, arguments: dict[str, Any], call_id: str) -> ToolResult:
        """Execute the tool and return a structured result."""
        ...

    def render_report(self, record: Any) -> str | None:
        """Render a markdown report section from a TraceEvent record.
        
        record has .input_json, .output_json, .status, .tool_name attributes.
        Returns None if no report should be generated for this record.
        """
        ...

    @staticmethod
    def can_handle(tool_name: str) -> bool:
        """Return True if this handler can process the given tool name."""
        ...


class ToolHandlerRegistry:
    """Registry mapping tool names to their handler instances."""

    def __init__(self, handlers: list[ToolHandler]):
        self._lookup: dict[str, ToolHandler] = {}
        for h in handlers:
            self._lookup[h.tool_name] = h

    def get(self, tool_name: str) -> ToolHandler | None:
        return self._lookup.get(tool_name)

    def list_names(self) -> list[str]:
        return list(self._lookup.keys())

    @classmethod
    def build_default(cls, *, market_repo, rag_service, memory_service,
                      strategy_service, backtest_service, world_model_service,
                      global_market_service, bitpro_adapter, live_service, **kwargs) -> "ToolHandlerRegistry":
        """Build a registry with all default handlers."""
        # Import handlers lazily to avoid circular imports
        from hypertrade.tools.handlers.market import (
            MarketSummaryHandler, MarketTickerHandler, MarketCandlesHandler,
            MarketCompareHandler, MarketIntelligenceHandler
        )
        from hypertrade.tools.handlers.rag import RagSearchHandler
        from hypertrade.tools.handlers.memory import MemoryWriteHandler, MemorySearchHandler
        from hypertrade.tools.handlers.strategy import (
            StrategyLibrarySearchHandler, StrategyExperimentPlanHandler, StrategyDraftHandler
        )
        from hypertrade.tools.handlers.backtest import BacktestRunHandler
        from hypertrade.tools.handlers.bitpro import BitProHandler
        from hypertrade.tools.handlers.live import LiveOrderIntentHandler
        from hypertrade.tools.handlers.world_model import (
            WorldModelSnapshotHandler, DefensiveActionHandler
        )
        from hypertrade.tools.handlers.global_market import GlobalMarketSnapshotHandler

        handlers = [
            MarketSummaryHandler(market_repo),
            MarketTickerHandler(market_repo),
            MarketCandlesHandler(market_repo),
            MarketCompareHandler(market_repo),
            MarketIntelligenceHandler(market_repo),
            RagSearchHandler(rag_service),
            MemoryWriteHandler(memory_service),
            MemorySearchHandler(memory_service),
            StrategyLibrarySearchHandler(strategy_service),
            StrategyExperimentPlanHandler(strategy_service),
            StrategyDraftHandler(strategy_service),
            BacktestRunHandler(backtest_service),
            BitProHandler(bitpro_adapter),
            LiveOrderIntentHandler(live_service),
            WorldModelSnapshotHandler(world_model_service),
            DefensiveActionHandler(world_model_service),
            GlobalMarketSnapshotHandler(global_market_service),
        ]
        return cls(handlers)
```

### kernel.py 改造

`_build_executor()` 从 ~350 行缩减为 ~50 行：

```python
def _build_executor(self, run_id, event_sink, ...) -> ToolExecutor:
    def execute_tool(tool_name: str, arguments: dict, call_id: str) -> dict:
        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            return self._tool_error_payload(call_id, f"Unknown tool: {tool_name}")

        # Governance check (universal, not tool-specific)
        policy = self._tool_registry.get_for_runtime_name(tool_name)
        if policy is None:
            return self._tool_error_payload(call_id,
                                            f"Unregistered tool: {tool_name}")

        decision = self._governance.evaluate(policy.policy, arguments)
        if not decision.allowed:
            self._log.warning("tool_denied", tool_name=tool_name,
                              reason=decision.reason)
            return self._governance_denial_payload(policy, decision, call_id)

        # Cancellation check
        if self._is_run_canceled(run_id):
            return self._tool_canceled_payload(call_id)

        # Timeout enforcement
        timeout = _timeout_for_class(policy.policy.timeout_class)
        start = time.time()

        try:
            result = handler.execute(arguments, call_id)
            elapsed = round((time.time() - start) * 1000)

            if result.error:
                self._log.error("tool_call_failed", tool_name=tool_name,
                                call_id=call_id, latency_ms=elapsed,
                                error=result.error)
                return self._tool_error_payload(call_id, result.error)

            self._log.info("tool_call_complete", tool_name=tool_name,
                           call_id=call_id, latency_ms=elapsed)

            # Emit trace event for SSE streaming
            self._emit_tool_event(event_sink, run_id, tool_name, call_id,
                                  "completed", arguments, result.payload)
            return result.payload

        except Exception as e:
            elapsed = round((time.time() - start) * 1000)
            self._log.error("tool_call_failed", tool_name=tool_name,
                            call_id=call_id, latency_ms=elapsed,
                            error=str(e), exc_info=True)
            return self._tool_error_payload(call_id, str(e))

    return execute_tool
```

`_render_planner_report()` 也委托给 handler：

```python
def _render_planner_report(self, records: list[TraceEvent]) -> str:
    sections = []
    for record in records:
        handler = self._tool_handlers.get(record.tool_name.replace(".", "_"))
        if handler and hasattr(handler, "render_report"):
            section = handler.render_report(record)
            if section:
                sections.append(section)
    return "\n\n".join(sections)
```

### Handler 拆分方案

每个 handler 作为独立模块，放在 `backend/src/hypertrade/tools/handlers/` 下：

| Handler 类 | 文件 | 覆盖工具 | 迁移自 kernel.py |
|------------|------|---------|-----------------|
| `MarketSummaryHandler` | `handlers/market.py` | `market_summary` | `_market_summary()` |
| `MarketTickerHandler` | `handlers/market.py` | `market_ticker` | `_market_ticker()` |
| `MarketCandlesHandler` | `handlers/market.py` | `market_candles` | `_fetch_market_candles()` |
| `MarketCompareHandler` | `handlers/market.py` | `market_compare` | `_market_compare()` |
| `MarketIntelligenceHandler` | `handlers/market.py` | `market_intelligence` | `_market_intelligence()` |
| `RagSearchHandler` | `handlers/rag.py` | `rag_search` | `_rag_search()` |
| `MemoryWriteHandler` | `handlers/memory.py` | `memory_write` | `_memory_write()` |
| `MemorySearchHandler` | `handlers/memory.py` | `memory_search` | `_memory_search()` |
| `StrategyLibrarySearchHandler` | `handlers/strategy.py` | `strategy_library_search` | `_strategy_library_search()` |
| `StrategyExperimentPlanHandler` | `handlers/strategy.py` | `strategy_experiment_plan` | `_strategy_experiment_plan()` |
| `StrategyDraftHandler` | `handlers/strategy.py` | `strategy_draft` | `_strategy_draft()` |
| `BacktestRunHandler` | `handlers/backtest.py` | `backtest_run` | `_backtest_run()` |
| `BitProHandler` | `handlers/bitpro.py` | 所有 `bitpro.*` 工具 | `_dispatch_bitpro_tool()` |
| `LiveOrderIntentHandler` | `handlers/live.py` | `live_order_intent` | `_live_order_intent()` |
| `WorldModelSnapshotHandler` | `handlers/world_model.py` | `world_model_snapshot` | `_world_model_snapshot()` |
| `DefensiveActionHandler` | `handlers/world_model.py` | `world_model.defensive_action` | `_defensive_action()` |
| `GlobalMarketSnapshotHandler` | `handlers/global_market.py` | `global_market_snapshot` | `_global_market_snapshot()` |

### Handler 示例

```python
# tools/handlers/market.py

from hypertrade.tools.handler_protocol import ToolHandler, ToolResult

class MarketSummaryHandler:
    tool_name = "market_summary"

    def __init__(self, market_repo):
        self._repo = market_repo

    def execute(self, arguments: dict, call_id: str) -> ToolResult:
        top_n = int(arguments.get("top_n", 20))
        tickers = self._repo.latest_tickers(limit=top_n)
        return ToolResult.ok(
            payload={"tickers": [t.to_dict() for t in tickers]},
        )

    def render_report(self, record) -> str | None:
        output = record.output_json or {}
        tickers = output.get("tickers", [])
        if not tickers:
            return None

        lines = ["## Market Summary", ""]
        lines.append("| Symbol | Price | 24h Change | Volume |")
        lines.append("|--------|-------|------------|--------|")
        for t in tickers[:10]:
            lines.append(f"| {t['inst_id']} | {t['last']} | "
                         f"{t.get('change_utc0_pct', 0):+.2f}% | {t.get('volume_ccy_24h', 0):,.0f} |")
        return "\n".join(lines)

    @staticmethod
    def can_handle(tool_name: str) -> bool:
        return tool_name == "market_summary"
```

---

## 实施步骤

1. **新建** `handler_protocol.py` — 定义 `ToolResult`、`ToolHandler` Protocol、`ToolHandlerRegistry`
2. **新建** `handlers/__init__.py` — 空文件
3. **逐个迁移 handler** — 从 kernel.py 对应方法中提取，保持业务逻辑不变
   - 先市场数据类（market.py）— 依赖最简单
   - 再 RAG/Memory 类 — 独立服务依赖
   - 再策略/回测类 — 内部服务依赖
   - 再 BitPro 类 — 外部适配器依赖（最复杂）
   - 最后 live/world_model 类
4. **改造 kernel.py**：
   - 构造函数接收 `tool_handlers: ToolHandlerRegistry`
   - `_build_executor()` 改为 registry lookup
   - `_render_planner_report()` 委托给 handler
   - 删除所有私有 handler 方法（`_market_summary`、`_market_ticker` 等）
5. **改造 main.py** — `AgentKernel` 构造时传入 `ToolHandlerRegistry.build_default(...)`
6. **改造测试** — `tests/test_agent_acceptance.py` 适配新构造函数

---

## 验收标准

1. `kernel.py` 的 `_build_executor()` 从 ~350 行降至 ~50 行
2. `kernel.py` 的 `_render_planner_report()` 从 ~1000 行降至 ~30 行
3. 添加新工具只需：新建 handler 文件 → 在 `build_default()` 中注册 → 在 `planner.py` 添加 tool schema（3 步，不改 kernel）
4. 每个 handler 的 `execute()` 返回 `ToolResult`，不直接调用 kernel 内部方法
5. 所有 254 个测试通过
6. `./scripts/check.sh` 通过

## 面试可讲点

- **策略模式**：将算法族（工具处理）封装为独立类，使它们可以互相替换
- **OCP（开闭原则）**：对扩展开放（新增工具不修改 kernel），对修改关闭
- **Protocol vs ABC**：Python 3.12 的 `Protocol` 提供 structural subtyping，比继承更灵活
- **单一职责**：Kernel 只管编排（governance → execute → emit → report），不再关心具体工具逻辑
- **依赖注入**：handler 通过构造函数接收依赖，不 import kernel，彻底解耦
