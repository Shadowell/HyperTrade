# Sprint 123 — Canonical Mission Event Reducer and Completion Proof

> 状态：Complete — 实现、全量验证、生产部署与只读 replay/hash canary 已关闭 Gate。
> 目标架构：[34 下一代专业 Agent Runtime](../architecture/34-next-generation-agent-runtime-audit-and-target-design.md)。

## Goal

让 Mission、PlanVersion、Step、Attempt、Budget 和交付终态都能仅从 append-only domain events 确定性重建，
并由独立 Completion Verifier 产生完成证明。Sprint 完成后，store 不再一边直接改 projection、一边追加不完整
事件；模型文本、worker 返回或 SSE EOF 均不能单独把 Mission 标记为完成。

## Dependencies

- Sprint 121–122 的 canonical event envelope、aggregate version、Thread/Turn/Item reducer 和 cursor replay 可用。
- 现有 Mission/PlanVersion/Step/Attempt、SQL lease、Evidence、Artifact 和 OperatorResponse 资产保持兼容输入。
- legacy Mission 记录只读兼容，不伪造无法还原的历史事件。

## In Scope

- 为 Mission、PlanVersion、Step、Attempt、Budget、Evidence binding 和 delivery 定义 versioned domain events。
- 所有状态、current step、usage、预算 reservation/consume/release、retry、replan 和 terminal 更新只通过 event reducer。
- event envelope 包含 aggregate/version、schema/reducer version、causation、correlation、actor、policy snapshot hash、
  payload hash、occurred/recorded time 和 fencing token。
- PostgreSQL 与 SQLite 使用相同 reducer 语义；online projection 与 offline replay 输出 canonical content hash。
- 版本 gap、重复冲突、未知 schema 或 stale fencing event 将 aggregate 置为 quarantine，并阻止继续 dispatch。
- 独立 `CompletionProofV1` 检查 success criteria、Evidence/Artifact、未完成 ToolCall、effect_unknown、预算和步骤终态。
- Turn 只有消费 validated Mission delivery 与有效 completion proof 后才能进入 `completed`。
- 提供 event upcaster/version policy；禁止通过修改旧事件内容解决 schema 演进。
- 为 legacy Mission 明确 `legacy_non_replayable` 投影，不声称可以从现有残缺事件重建。

## Out of Scope

- Tool Approval、外部写副作用 reconciliation 和 live order exactly-once；属于 Sprint 124。
- Outcome/Lesson 学习；属于 Sprint 125。
- 重写所有 Planner、Context Engine 或 Capability handler。
- 为旧 Mission 伪造缺失 event，或双写新旧 projection 作为永久方案。
- paper/Testnet/live/order/capital 权限变化。

## Done Means

1. 从空数据库按 committed events 重放后，Mission/Plan/Step/Attempt/Budget/delivery projection hash 与线上完全相同。
2. `update_usage`、`set_current_step`、replan、retry、pause/resume/cancel 和 terminal transition 均有完整 event。
3. 随机合法命令序列的 property tests 不产生非法状态、负预算或第二个终态。
4. aggregate version gap、冲突重复、未知 reducer version 和 stale fencing token 均 fail closed 并 quarantine。
5. provider 文本、工具成功或 worker 返回不能直接产生 `completed`；必须存在 `CompletionProofV1(pass)`。
6. 存在未完成 ToolCall、effect_unknown、无效 Evidence 或未满足 criteria 时 completion proof 必须失败并列出 gaps。
7. worker 在 event append、projection reduce 和 terminal delivery 边界崩溃后可恢复，且不丢 committed event。
8. Turn 与 Mission 的 terminal event 恰好一次，SSE 重连不会重复应用。
9. legacy Mission 被正确标记为不可完整重放，历史读取不被破坏。
10. 本 Sprint 前后 paper、Testnet、live、订单和资金状态不变。

## Verification

```bash
uv run pytest tests/test_mission_domain_events.py -q
uv run pytest tests/test_mission_reducer_replay.py -q
uv run pytest tests/test_mission_completion_proof.py -q
uv run pytest tests/test_mission_worker_faults.py -q
uv run pytest tests/test_thread_turn_replay.py -q
./scripts/check.sh
git diff --check
```

生产 canary 仅使用受控只读 Mission：抓取 committed event，离线重放并比较 hash；在 canary 前后确认没有 legacy
Run/Task 写入和任何交易 mutation。

### Local Implementation Evidence

- V2 envelope、deterministic reducer、SQL/内存 projection、worker fencing、quarantine 和 migration `0031` 已实现。
- 独立 `CompletionProofV1` 已接入 Mission terminal transition 与 Thread delivery；无当前 passing proof 不得完成。
- reducer/replay/proof/worker fault、Alembic 及既有 Mission/Thread 回归测试通过；完整 `./scripts/check.sh` 通过，
  包含 frontend 15 tests/build、Ruff、严格 mypy 与 Python 699 tests（保留 2 个既有 OKX coroutine warnings）。
- 实现提交 `30e5b6e` 与 lease/hash 修复 `c33f8e5` 均已部署；最终流水线 `29815455839` 成功。
- 首次生产 canary 捕获 terminal transition 后 ORM lease 清理覆盖 reducer `updated_at`，导致在线/离线 hash
  不一致；已将 lease 清理移到 projection 持久化前，并补充带 fencing lease 的 SQL 回归测试。修复后的完整
  `./scripts/check.sh` 再次通过。
- 修复后新建只读 Mission `mis_640f994776654f14a704`：17 个 V2 events 连续重放，online/offline hash 均为
  `fb26c8ec831a281f2e7637f83f932427a5e97259c44847e9af1d923f39a7666a`；CompletionProof 通过且版本绑定，
  completed 终态恰好一次，cursor 末端无重复。计划仅含只读 inspection/market capability。
- canary 前后 legacy task、live intent、paper position/fill 可见记录 ID 不变；最新 50 条 Mission 中 33 条
  历史记录保持 `legacy_non_replayable`，没有伪造历史事件。

## Handoff

Sprint 124 在该事件与完成语义上实现 Approval、write-ahead dispatch、effect_unknown 和 reconciliation。
