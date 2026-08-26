# User-Directed Contract — 现有策略进化闭环（M0 Handoff 第一步）

> 状态：Active。
>
> 激活原因：产品所有者于 2026-08-25 确认 C→A 路线——先统一证据口径，再对 BitPro
> 现有 running 策略启动进化闭环。本合同即 [M0 合同](user-directed-autonomous-strategy-research-loop-m0.md)
> Handoff 第 1 步的落地合同。
>
> 前置关系：ARC 真身闭环合同（Delivered）验证了研究侧全链；本合同不触碰新策略发现，
> 只做"已有策略的参数邻域进化 + 同口径比较"。Live 边界不变。

## Goal

回答一个问题：

> 系统能否对一个**真实在跑**的策略，自主产出同口径、可证伪的 Challenger，并用双方都
> 无法质疑的证据判断它是否优于 Champion——全程无需人工拼接 API。

 ARC 研究循环已证明能诚实拒绝坏候选；本合同证明它能**有依据地改进好策略**。

## User-Visible Outcome

操作员指定一个 running 策略后得到：

1. 该策略的衰减评估投影：结算 Outcome 数、BitPro 证据数、衰减分类、unknowns 清单。
2. 若衰减成立：不可变 Challenger 版本（参数邻域内）+ 与 Champion **同窗口、同成本、
   同数据源**的 BitPro 回测对比报告。
3. 明确结论三选一：`challenger_superior` / `not_superior` / `needs_data`——前两者必须
   绑定双侧回测 ref，后者必须列出缺口。
4. 全过程可重放：每个数字都有来源引用，比较口径在报告里自述。

## In Scope

- **口径统一（Slice 1）**：定义并钉死比较裁判——Champion/Challenger 的比较指标只认
  BitPro 自有回测结果（同一引擎、同一窗口、同一成本模型）；本地回放恒为
  `prefilter_only`，其指标不得出现在任何晋级/比较结论里。新增校准测试度量双引擎漂移。
- **现状分析投影（Slice 2）**：running 策略的只读分析视图——结算 Outcome、BitPro 证据、
  衰减分类（复用 `StrategyEvolutionService.assess_decay`），输出进化候选清单。
- **Challenger 创建（Slice 3）**：经 `research/codegen.py` 在父版本参数邻域内生成
  Challenger spec；走既有 Discovery 新颖性登记 + BitPro validate/create；
  Champion 与 Challenger 各跑一次**同参数** BitPro 回测（同 start/end/symbol/timeframe/
  初始资金），比较报告绑定双侧 backtest ref。
- **结论裁决（Slice 4）**：确定性裁判——OOS 指标对比 + 交易数下限 + 回撤约束 +
  成本口径一致；`challenger_superior` 需要样本外夏普更高且回撤不劣且折间一致。
  比较结果写入 StrategyOutcome Ledger（Sprint 125 资产）。
- 生产实测一条真实 running 策略的全流程。

## Out of Scope

- 新策略发现（ARC 发现循环保持独立）；多策略组合优化。
- 自动实盘晋级：`challenger_superior` 只产生受治理的 Paper 推进建议，
  Live 仍需 Sprint 132–134 显式激活。
- 本地回放引擎与 BitPro 引擎的代码合并（只统一裁判权，不合并实现）。
- 参数以外的结构变异（规则槽位变更留给后续合同）。
- StockPro adapter（Handoff 最后一步，另行立项）。

## Safety Boundaries

1. 比较指标唯一来源是 BitPro 自有回测结果；本地回放指标进入任何比较结论即为缺陷。
2. Challenger 是新的不可变 StrategyVersion；禁止原地修改 Champion。
3. 双侧回测参数必须逐字段相等并在报告中可见；任何不一致 → 结论作废为 `needs_data`。
4. `challenger_superior` 不自动执行任何 paper/live 写动作——只产出建议与证据链。
5. LLM 可参与衰减解释与假设生成；比较裁决、窗口选择、成本模型全部确定性。
6. 单次损失/陈旧证据/未知副作用不得触发"优化成功"结论（继承 Sprint 127 边界）。

## Implementation Slices

### Slice 1 — 口径统一合同

- 比较裁判常量化：比较类 ToolResult/报告只接受 `bitpro_mcp:*` 来源引用。
- 校准测试：同一策略同一窗口分别跑本地回放与 BitPro 回测，记录夏普/回撤/交易数
  漂移到校准报告（诊断用途，不入裁决）。
- Done：比较路径上出现非 BitPro 来源即测试失败；校准报告落盘。

### Slice 2 — 现状分析投影

- 只读 API：给定 running 策略 → 衰减评估 + 证据链 + 是否满足进化前置
  （≥2 结算 Outcome、无 unknown 数据缺口）。
- Done：对生产 11 个 running 策略出真实投影；不满足前置的明确列出缺口。

### Slice 3 — Challenger 创建与同口径比较

- 进化候选生成（参数邻域）→ Discovery 登记 → BitPro validate/create。
- 同参数双侧 BitPro 回测 + 确定性比较裁决 + Ledger 写入。
- Done：Fake BitPro 黄金测试全流程；真实策略跑通一次（无论结论方向）。

### Slice 4 — 生产实测收口

- 选一个真实 running 策略完整走一遍，结论如实入档（`docs/progress.md`）。
- Done：progress 记录含双侧回测 ref、比较数字、结论及理由。

## Done Means

1. 比较结论只引用 BitPro 回测来源（测试钉死）。
2. 一条真实策略完成 Champion/Challenger 同口径比较，结论三选一且有双侧 ref。
3. 所有比较参数逐字段相等且在报告中可见。
4. `challenger_superior` 未触发任何自动 paper/live 写动作。
5. `./scripts/check.sh` 通过；新增测试覆盖上述每条。

## Verification

```bash
uv run pytest tests/test_evolution_caliber.py -q
uv run pytest tests/test_evolution_handoff.py -q
./scripts/check.sh
```

生产验证：对一条真实 running 策略执行 Slice 2–3，结果入 progress。

## Handoff

- `challenger_superior` 且 Paper 推进建议成立时 → 触发 Sprint 130 治理面真实执行。
- 稳定后 → Research Trigger 接入（自动预算研究）→ StockPro adapter。
