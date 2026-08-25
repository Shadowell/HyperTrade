# Sprint Contract: Agent-Authored Strategy Code into the Validation Funnel (主线融合)

## Sprint Name

`agent-strategy-code-fusion`

## Goal

打通「agent 在代码工作区写真策略代码 → 沙箱测试 → ARC 静态门禁 → BitPro 回测 →
证据门禁 → 模拟盘晋升」的全链。此前 agent 只能在 6 家族模板目录里选参数；
本合同后 agent 可以写任意符合 BaseStrategy 契约的实现，先在沙箱用真实 pytest
验证行为，再经与 codegen 产物**同一**静态门禁（`static_code_rejections` 单一
事实来源）预检，然后走既有 BitPro 主线工具链。

## In Scope

- 工作区自动注入 BitPro 契约 stub（系统注入、agent 不可写）：
  - `app/core/execution/base_strategy.py`：内存版 BaseStrategy（orders 记录、
    symbols()/open_contract/close_contract/on_init/on_bar 契约面）。
  - 包 `__init__.py` ×3 + `tests/conftest.py`（sys.path 注入工作区根），
    使 `from app.core.execution.base_strategy import BaseStrategy` 在 pytest 下可导入。
- 新工具 `research.validate_strategy_code`（read）：读工作区文件 →
  ast.parse + `static_code_rejections` → 结构化判定（reason codes + sha256
  内容哈希 + 下一步指引）。与 codegen 产物同一门禁，fail-fast 省回测预算。
- system prompt 主线路由更新（workspace 写码 → pytest → 静态门禁 →
  bitpro_strategy_create → 回测 → 门禁 → 晋升）。

## Out of Scope

- ARC HistoricalEvidenceGate 直接接工作区代码（bar-replay 走既有 BitPro
  回测路径，证据语义不变）。
- 策略代码的参数扫描/变异（ARC mutator 不动）。
- 生产 UDS 沙箱 runner 接线。

## Deliverables

- `agent/workspace.py`：stub 注入 + 防覆盖。
- `tools/registry.py` + `agent/kernel.py`：新工具。
- `tests/test_agent_workspace.py` 增补：stub 契约面、防覆盖、
  真实 BaseStrategy 策略 + 测试的 pytest 通过、静态门禁工具判定。

## Done Means

- agent 写一个真实 BaseStrategy 子类 + 单测，沙箱 pytest 通过。
- `research.validate_strategy_code` 对 codegen 风格代码返回 passed，对
  违规代码返回 reason codes；内容哈希稳定。
- agent 不可覆盖系统注入的 stub 文件。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_agent_workspace.py tests/test_tool_registry.py
./scripts/check.sh
```

## Risks / Notes

- stub 是内存简化版（orders 记录而非真实撮合）——仅用于行为单测；真实绩效
  判定仍以 BitPro 回测为准，证据语义不变。

## Handoff

- Next likely step: P2 深度项（红队重放 / evals 进 CI）。
