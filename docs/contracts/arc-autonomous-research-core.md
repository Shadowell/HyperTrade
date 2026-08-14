# User-Directed Contract — ARC (Autonomous Research Core)

> 状态：Closed。
> 关闭日期：2026-08-01。
> 关闭依据：ARC Sprint 132–135 全部交付并验收，QA 见 `docs/qa/arc-autonomous-research-core.md`；
> `./scripts/check.sh` 全绿（frontend lint/test/build、Ruff、严格 mypy、871 pytest）。
> 激活原因：产品所有者明确要求实现通用 ARC (Autonomous Research Core) 自主进化控制内核，具备自主探索、代码突变演进、因果反思与红蓝对抗能力，并在达标后自动上线模拟盘运行。
> 优先级：最高。主线全速推进，主网实盘交易保持禁用。

> 编号说明：本合同的 Sprint 132–135 是 **ARC 内部**开发阶段，与
> `docs/contracts/sprint-132-live-trading-mandate-risk-engine.md`、
> `sprint-133-live-canary-execution-reconciliation.md`、
> `sprint-134-authorized-autonomous-portfolio-pilot.md`（北星实盘 Gates 4–5）编号重叠但**相互独立**。
> 北星实盘合同仍处于 `Awaiting explicit owner approval`，未因本合同关闭而激活。

## Goal

构建通用自主进化 Agent 控制内核 **ARC (Autonomous Research Core)**：

> 用户提交一次自然语言策略目标；ARC 自主进行候选假设搜索、代码基因突变、真实 BitPro 沙箱校验与回测；由红蓝对抗引擎（蓝队策略发明 vs. 红队攻击找茬）与确定性验证器进行审查；失败实验自动归因反思存入 Reflexion 账本并指导下一轮演化；通过审核的策略在用户预授权边界内自动上线模拟盘运行。

## Sprints

1. **Sprint 132**: ARC 通用内核、领域合同与黄金测试 (`ARCController`, `ARCGoalV1`, State Machine)
2. **Sprint 133**: ARC 策略基因突变与红蓝对抗引擎 (`ARCGeneticMutator`, `ARCAdversarialEngine`)
3. **Sprint 134**: ARC 因果归因反思账本与经验继承 (`ARCReflexionLedger`, Negative Constraints)
4. **Sprint 135**: ARC 自动模拟盘孵化与端到端自主探索闭环 (`ARCPaperIncubationResolver`, Acceptance Testing)

## Safety & Boundaries

- `live_allowed` 恒为 `false`，主网实盘保持物理禁用。
- 模型只能提出假设、突变代码、红蓝对抗陈述与反思总结。
- 确定性验证服务做独立终审裁决。
- 模拟盘上线使用预授权派生的 candidate-bound 窄授权。

## Addendum — 2026-08-15 一次实盘审批

产品入口仍是 ARC。`live_allowed` 仍不可构造为 True。实盘不再从 goal 开关打开，只经
`GET/POST /api/v1/arc/missions/{id}/live-approval`：观察窗证据齐全后操作员批一次，再走
审批绑定的 `authorized_live_promote`。`call_tool` 对 `live_promote` / 下单 / 划转继续拦截。
