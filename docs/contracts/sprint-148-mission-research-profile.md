# Sprint Contract: Mission Research Profile (P1 主线阻塞项)

## Sprint Name

`mission-research-profile`

## Goal

生产实弹发现：chat 流量 100% 走 mission 运行时，而 agent 原创策略能力
（代码工作区 / 静态门 / BitPro 写工具）只在 AgentKernel——chat 主线够不着。
本合同把这些能力补进 mission capability 目录，并引入显式 operator 开关的
`research.v1` 权限档（默认仍 read_only.v1），使「agent 写策略 → 沙箱测试 →
静态门 → BitPro 回测 → 门禁」在 mission 主线上可规划、可执行、可审计。

## In Scope

- 目录新增 6 能力：`workspace.write_file` / `workspace.run`（research_write +
  幂等必填）、`research.validate_strategy_code`（read）、`bitpro.strategy_create` /
  `bitpro.backtest_start`（research_write + 幂等必填）、`bitpro.backtest_result`（read）。
- `research.v1` 权限档：`CatalogCapabilityPolicy` 与 executor `_preflight`
  允许 read+research_write；`read_only.v1` 行为逐字节不变。
- chat mission 权限档开关 `MISSION_RESEARCH_PROFILE_ENABLED`（默认关；
  开启时 prompt 派生 mission 用 research.v1，约束文本同步声明写边界）。
- LLM planner 信封按 mission 权限档过滤（research 档含 research_write 能力；
  确定性 fallback 仍只读）。
- handlers：per-mission `AgentWorkspace` 缓存 + BitPro 写 handler
  （strategy_create / backtest_start[wait] / backtest_result）。

## Out of Scope

- paper_write/testnet_write/live_write 能力（mission 面仍不碰交易写）。
- ARC 引擎、kernel 工具面（已就绪）。
- backtest 轮询式多步等待（wait_for_result=True + 300s 超时上限）。

## Deliverables

- `capability_catalog.py` / `tool_runtime.py` / `entrypoint.py` / `research_planner.py` / `config.py`。
- `tests/test_mission_research_capabilities.py`：目录策略一致性、双权限档行为、
  planner 信封过滤、executor 端到端（workspace 写+跑 pytest 真通过）、
  bitpro 写 handler（fake adapter）、entrypoint 开关。

## Done Means

- flag 开 + research.v1 mission：LLM planner 可规划并执行 workspace 写、
  沙箱 pytest、静态门、BitPro 建策略与回测。
- flag 关：一切行为与现状逐字节一致。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_mission_research_capabilities.py tests/test_mission_llm_planner.py
./scripts/check.sh
```

## Risks / Notes

- research.v1 只放行 research_write；paper/testnet/live 写在目录层面就不存在，
  planner 信封也看不见。
- BitPro 写走既有幂等键派生（mission+plan+step+arguments 哈希）。

## Handoff

- Next likely step: 第二轮实弹（chat 全链 authored-code）。
