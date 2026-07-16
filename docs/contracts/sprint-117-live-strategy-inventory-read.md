# Sprint 117 — BitPro Live Strategy Inventory Read

> 状态：Completed — 2026-07-16。

## Goal

让 Mission-first Agent 能将“我的实盘策略有哪些”路由到 BitPro 的受治理只读实盘策略清单，而不是
错误地降级为 RAG/Memory 搜索。

## In scope

- 增加经过审查的 `bitpro.live_strategy_summary` Mission capability，`scope=read`、
  `side_effect=none`，并仅使用 `bitpro-mcp-v1` 的 capabilities → health → live-strategies
  预检链路。
- 对“实盘策略 / live strategy”清单和诊断请求采用该能力；不混入本地回测、RAG 或 Memory 结果。
- 对“有哪些”完整列出最多 20 条策略名称、运行状态和标的；收益/损益等诊断字段仅留在受审计的
  有界载荷中，并为每条可见策略绑定 BitPro 来源。
- 数据源不可用或返回空清单时明确返回数据缺口；不得编造策略或把无关记忆作为证据。
- 为精确中文提问、受治理执行、空结果和外部不可用路径增加回归测试；生产只读冒烟仅记录
  合同版本、健康状态和聚合策略数。

## Out of scope

- 创建、更新、启停、推广或删除任何 BitPro 策略。
- 读取账户凭证、原始订单/持仓序列，或开放主网订单、资金调拨和资本分配。
- 将 BitPro 业务逻辑、策略存储或实时数据复制到 HyperTrade 数据库。

## Done means

- “我的实盘策略有哪些”计划仅包含目标检查和 `bitpro.live_strategy_summary`，不调用 RAG、Memory
  或本地回测能力。
- 每条可见策略事实带 BitPro MCP source ref；无结果和不可用状态没有伪造证据。
- 该能力仍受 Catalog schema、read-only policy、timeout/circuit、bounded preview 和审计观察约束。
- 真实 BitPro 只读预检确认 `bitpro-mcp-v1`、health 和 live strategy 清单可用；不记录策略正文、
  原始响应或任何凭证。

## Verification

```bash
uv run pytest tests/test_research_mission_planner.py tests/test_capability_catalog.py \
  tests/test_live_strategy_capability.py -q
./scripts/check.sh
```

Production smoke sequence: `bitpro_capabilities` → `bitpro_health` → `live_strategies`; report only
contract version, source health, aggregate count and field coverage.

## Acceptance record

- Local `./scripts/check.sh` passed frontend lint/test/build, Ruff, strict mypy and the Python suite;
  focused routing/catalog/runtime/operator-response tests and desktop test/build also passed.
- Deployment workflow `29462538867` completed successfully for commit `44f2cae`.
- Production health returned `ok`. The exact Chinese request completed through the Mission stream with
  `answer_delta → evidence_ready → final`; its public result had one verified BitPro evidence group,
  20 BitPro strategy source references, 20 visible inventory rows and no unknowns. No strategy text,
  raw response, credential or account data was recorded in this acceptance note.

## Handoff

The capability remains read-only and belongs to BitPro as source of truth. Follow-up work may add
multi-turn strategy drill-down only after the declared conversation-context gap is implemented and
evaluated; it must not reuse the prior turn by guessing.
