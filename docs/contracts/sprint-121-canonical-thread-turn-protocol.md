# Sprint 121 — Canonical Thread/Turn Protocol for Remote CLI

> 状态：Complete — 2026-07-21 已完成实现、全量回归、生产部署和只读 canary 验收。
> 目标架构：[34 下一代专业 Agent Runtime](../architecture/34-next-generation-agent-runtime-audit-and-target-design.md)。

## Goal

把 Remote CLI 的 `ht ask` / `ht chat` 从 legacy `/api/agent/runs` 和客户端隐式历史切换到服务端持久化的
Thread/Turn/Item 协议。Sprint 完成时，两轮会话必须由服务端恢复正确目标，事件可以确定性重放，SSE
断线可以续传，并且该路径不再新写 `AgentRun` 或 `AgentTask`。

这是一个交互协议垂直切片，不是完整 Agent Runtime 重写。它只迁移一个 surface，并复用现有 read-only
Mission capability 与 OperatorResponse，避免同时扩大工具、交易或多 Agent 范围。

## In Scope

### Domain and persistence

- 新增最小 `Thread`、`Turn` 和 tagged `Item` 领域合同；Thread 是对话聚合，Turn 是一次输入到终态，Mission
  是可选关联的长任务，三者不得互相伪装。
- 新增 versioned domain event envelope：event/aggregate/schema version、causation/correlation、租户级
  idempotency、actor、policy snapshot hash、payload hash、occurred/recorded timestamps。
- 所有新 projection 只能由 deterministic reducer 更新；同一 event log 离线重放必须得到相同 hash。
- PostgreSQL/SQLite migration、SQL store、in-memory test store、必要索引与约束。
- `client_message_id` / idempotency key 在 tenant + Thread scope 唯一；相同 key、不同 request hash 返回 409。

### Protocol

- `POST /api/agent/v1/threads`：创建 Thread。
- `GET /api/agent/v1/threads/{thread_id}`：读取 bounded Thread projection。
- `POST /api/agent/v1/threads/{thread_id}/turns`：写入用户 Item 并开始 Turn。
- `GET /api/agent/v1/threads/{thread_id}/turns/{turn_id}`：读取 Turn/Item 终态。
- `GET /api/agent/v1/threads/{thread_id}/events?after=` 与 `/events/stream`：cursor replay + SSE。
- 最小 `POST .../turns/{turn_id}/interrupt`，只允许取消尚未终态的 Turn。
- 公开 Item 生命周期至少包括 `user_message.completed`、`turn.started`、`tool_call.started/completed`、
  `evidence_ready.completed`、`agent_message.delta/completed` 和 `turn.completed|failed|cancelled`。
- SSE 正常 EOF 前必须有 terminal Turn event；无 terminal event 的 EOF 是客户端错误，不投影为 completed。

### Runtime integration

- Turn 从服务端 persisted Items 编译 conversation context；新 API 不接受 `prior_turns`。
- resolved context 记录明确的 subject/symbol/strategy/account/environment refs；无法安全解析时进入 input gap，
  不能猜测。
- 复用现有 Mission Runtime 执行 read-only capability；Turn 记录关联 Mission id，并把 Mission delivery 转为
  canonical Item，而不是把 Mission 伪装成 AgentRun。
- 现有 ContextPack 必须包含服务端 Thread facts；本 Sprint 不重写通用 Planner/Verifier。
- worker lease 与 Turn 终态事件关联；worker 崩溃恢复不得创建重复 Turn 或重复 read ToolCall。

### Remote CLI cutover

- Remote `ht ask` 创建单 Turn Thread；是否保留 Thread 由 CLI 参数/默认 retention 明确决定。
- Remote `ht chat` 首次创建 Thread，后续每次输入只提交 `thread_id + user input + client_message_id`。
- CLI 从 canonical Item stream 渲染状态、工具进度、证据和最终回答。
- 删除/禁用 Remote CLI 对 `/api/agent/runs`、legacy run-shaped final 和 `prior_turns` 的自然语言依赖。
- API 可暂时保留 legacy `/api/agent/runs` 供未迁移 Web/Desktop 使用，但不能由新 CLI 写入，也不做双写。

### Verification and documentation

- domain/property tests、API contract tests、SQL reducer/replay tests、SSE reconnect tests、worker crash tests、
  Remote CLI subprocess E2E。
- 更新 README、spec、architecture/progress、API/user/developer docs 中与 Remote CLI 相关的事实描述。
- 记录 legacy adapter 的调用者和删除条件；不得把兼容层写成新的 canonical API。

## Out of Scope

- Web、Desktop、Textual TUI 的协议迁移；它们属于后续独立 vertical slice。
- 删除历史 `AgentRun`/`AgentTask` 数据或其只读查询。
- 重写完整 Mission Planner、Context Engine、Verifier、Completion Engine 或 OperatorResponse。
- 接入生产多 Agent Supervisor；`deterministic_worker()` 删除属于后续 Sprint。
- paper create/pause/close/reset、Testnet 下单或任何 live write。
- 新 Capability、新数据源、新策略、模型自主学习或自动晋级。
- 伪造旧 Run/Task 历史 event；旧记录只作为 legacy history 展示。
- 永久双写、Redis/Celery/Temporal 或与本切片无关的新基础设施。

## State and event minimum

### Thread

- `active`：可接受 Turn；同一时刻最多一个普通 active Turn。
- `archived`：只读，不接受新 Turn。

### Turn

`accepted → contextualizing → running → streaming → completed`，并支持 `waiting_input`、`failed`、
`cancelled`、`expired`。`running/streaming → completed` 只能由 validated Mission delivery 触发；provider 文本
或流关闭本身不能完成 Turn。

### Required guards

- terminal Turn 不可重新进入 active 状态。
- `interrupt` 在 terminal Turn 上幂等返回既有终态，不追加第二个 terminal event。
- reducer 只接受连续 aggregate version；版本 gap 将 Thread quarantine 并阻止运行。
- stale fencing token 的 worker event 被拒绝。
- factual agent message 必须引用现有 Evidence/source 或显式 unknown。

## Done Means

1. 真实 Remote CLI 会话连续输入：
   - `比较 momentum_breakout_v1 和 mean_reversion_v1 哪个收益更高？`
   - `后者最大回撤多少？`

   第二个 Turn 的 canonical resolved subject 必须是 `mean_reversion_v1`；若该策略没有可比证据，回答必须
   明确该策略的数据缺口，不能回答前者或其他策略。
2. `ht ask '看下 LAB 的价格'` 仍返回精确 `LAB-USDT-SWAP` 事实和来源；`主网满仓买入 ETH` 仍在工具前阻断。
3. 相同 `client_message_id` 和 payload 重发返回同一 Turn；相同 key 不同 payload 返回 409。
4. 任意 cursor 断开重连后，Item 不丢失、不重复应用，且恰好一个 terminal Turn event。
5. 将 committed events 读入离线 reducer，Thread/Turn/Item projection hash 与 online store 完全相同。
6. 在 worker 的 claim、dispatch-intent、tool-return、terminal-event 边界注入崩溃时，不出现重复 ToolCall、
   false completed 或 lost committed event。
7. 在该 Remote CLI 流程前后，legacy `agent_runs` 和 `agent_tasks` 行数增量均为 0。
8. CLI/API 不提交、不接受 `prior_turns`；server persisted Items 是唯一 conversation context source。
9. false completed、unsafe dispatch、ungrounded visible factual claim、wrong symbol/strategy target 均为 0。
10. 本 Sprint 不新增 paper/Testnet/live/order/capital mutation capability 或 credential。

## Verification

最小命令集；实现时补充精确 test module 名称，但不得用删除断言或放宽 evaluator 通过：

```bash
uv run pytest tests/test_thread_turn_domain.py -q
uv run pytest tests/test_thread_turn_api.py tests/test_thread_turn_replay.py -q
uv run pytest tests/test_thread_turn_worker_recovery.py -q
uv run pytest tests/test_cli_thread_turn_e2e.py -q
uv run pytest tests/test_agent_missions.py tests/test_mission_worker.py -q
./scripts/check.sh
git diff --check
```

部署/canary 验收必须使用受控只读请求：

- 创建新 CLI Thread，执行上述两轮策略指代案例并检查 persisted resolved subject。
- 执行 LAB 精确行情和主网阻断案例。
- 在 SSE 中途断开一次，以最后 cursor 重连，确认最终回答和单一 terminal event。
- 比较 canary 前后 `agent_runs` / `agent_tasks` row count，必须无新增。
- 从 event 运行离线 replay/hash compare；不读取 production secret 或保存原始敏感 payload。

## Handoff

Sprint 完成后，[Sprint 122](sprint-122-canonical-thread-turn-web-cutover.md) 只迁移 Web natural-language
workspace 到同一协议，并删除 Web 对 legacy run projection 的完成判断。Sprint 121 未完成前，不开始
Desktop/TUI/multi-agent/paper-write 切片。

后续开发者必须保留以下假设，若不成立先更新本合同和 spec：

- Mission Catalog 在本 Sprint 仍为只读；
- 一个 Thread 同时只运行一个普通 Turn；
- legacy `/api/agent/runs` 仅为未迁移 surface 的临时兼容层，有删除期限；
- event payload 不保存 secret、无限工具原文或 private reasoning；
- rollback 不恢复 legacy 写路径，只能暂停新 surface 或切回上一版 canonical client。
