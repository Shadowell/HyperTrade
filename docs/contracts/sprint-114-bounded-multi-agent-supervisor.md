# Sprint 114 - Bounded Multi-Agent Supervisor

> 状态：Active；Sprint 113 Gate J2 已于 2026-07-15 关闭。

## Goal

建立受角色目录、原子预算、依赖图和结构化交接约束的多 Agent Supervisor。并行只用于相互独立的
只读研究 assignment；写操作严格串行。冲突、少数证据和 unknown 必须进入 ledger，不能由多数
投票或最后写入者覆盖。

## In Scope

- RoleDefinitionV1/RoleCatalogSnapshotV1、AssignmentV1、BudgetReservationV1、HandoffV1、
  CritiqueV1、ConflictV1、MergeDecisionV1。
- reviewed Role Catalog；首批角色：research_lead、market_analyst、evidence_analyst、critic，均有
  capability/context/permission allowlist 和 max concurrency。
- Supervisor deterministic team selection；最多 4 个 assignment、无角色自建、无无限 debate。
- AnyIO TaskGroup 并发只读 assignments；依赖 DAG、单 Agent fallback、per-role timeout/circuit。
- 原子 Mission budget reservation/commit/release，所有并发分支总和不能超过剩余硬预算。
- Handoff 必须绑定 Context Pack、Artifact/Observation/source refs、unknowns 和 output hash；禁止
  transcript、raw provider output、private reasoning。
- Critic/merge schema；冲突按字段/claim/source 保存，merge 只能 resolved 或 explicit unknown。
- migration `0026_agent_supervision`；assignment/handoff/conflict/merge API 和 Mission events。

## Out of Scope

- 自由对话群、角色自我复制、动态权限扩张、无限并行或无限辩论。
- Sprint 115 shell/code/Docker sandbox 和 BitPro import。
- paper/live/order/capital 并发写入；本 Sprint 不增加任何写 capability。
- 用 Agent 数量代替质量证明；动态团队默认关闭。

## Done Means

- role/capability/permission/context 不匹配在 assignment 执行前失败，调用次数为零。
- 最多 4 个只读 assignment 并行；所有 write/approval assignment 被拒绝或串行化。
- 并发 reservation 原子且总量不超过 Mission 剩余 tokens/tool/model/duration budgets。
- timeout/cancel 后 reservation 可审计地 release；已 commit usage 不回滚。
- Handoff schema 来源覆盖 100%，不含 transcript/raw/secret/reasoning；hash 可重放。
- 矛盾 claim 形成 Conflict ledger；未解决冲突在 merge 中保持 unknown。
- 单 Agent fallback 与 team path 都能满足同一安全/完成门禁。
- 全仓检查、migration 往返、production flag-off 和只读 canary 通过。

## Verification

```bash
uv run pytest tests/test_role_catalog.py tests/test_multi_agent_supervisor.py -q
uv run pytest tests/test_agent_missions.py tests/test_context_compiler.py -q
./scripts/check.sh
```

Required scenarios: role denial, max-team denial, parallel timing, dependent ordering, atomic budget
race, timeout release, cancellation, handoff source validation, unsafe payload refusal, conflict
preservation, merge unknown, deterministic fallback, SQL restart and authenticated API projection.

## Handoff

Gate K 通过后才激活 Sprint 115。Sandbox 只能消费审核后的 assignment、Context Pack 和 Artifact
refs，不能获得 Supervisor、数据库、Docker socket、交易权限或生产 secrets。
