# Sprint 122 — Canonical Thread/Turn Web Cutover

> 状态：Proposed；仅在 Sprint 121 完成并通过生产只读验收后进入开发。
> 上游合同：[Sprint 121](sprint-121-canonical-thread-turn-protocol.md)。

## Goal

把 Web Harness 的自然语言工作区从 legacy `/api/agent/runs`、浏览器侧历史拼接和 run-shaped 完成判断，
切换到服务端拥有的 `Thread → Turn → Item` 协议。Sprint 完成时，Web 与 Remote CLI 消费同一状态、事件、
证据和终态合同，并且 Web 请求不再新增 `AgentRun` 或 `AgentTask`。

## Dependencies

- Sprint 121 已交付 canonical Thread/Turn API、event reducer、SSE cursor recovery 和 Remote CLI cutover。
- Sprint 121 的真实两轮指代、LAB 精确行情、主网阻断和 legacy row-count 门禁全部通过。
- 本 Sprint 复用 Sprint 121 服务端协议，不创建 Web 专用状态机或第二套 history schema。

## In Scope

- Web 创建、恢复、归档 Thread，并在同一 Thread 内提交 `client_message_id + user input`。
- Web 从 canonical Item stream 渲染用户消息、工具进度、Evidence、warning、回答 delta 和单一 Turn 终态。
- 页面刷新、SSE 断开和浏览器重新打开后，使用服务端 cursor 与 persisted Items 恢复，不重放用户请求。
- Web 当前目标、symbol、strategy、account 和 environment 只展示服务端 resolved refs，不在客户端重新推断。
- 同一 `client_message_id` 重试保持幂等；payload 冲突展示明确错误，不静默创建新 Turn。
- 迁移 Web query/cache/state 类型，删除自然语言路径对 legacy run-shaped final、`prior_turns` 和本地完成判断的依赖。
- 保留历史 `AgentRun`/`AgentTask` 只读入口，并显式标为 legacy history。
- 为 canonical loading、waiting_input、waiting_approval、streaming、failed、cancelled 和 reconnecting 状态提供 UI。

## Out of Scope

- Desktop、Textual TUI 和 Local CLI 协议迁移。
- 删除 legacy 数据表、历史记录或仍未迁移 surface 的兼容读取 API。
- 重写 Mission Planner、Capability Catalog、Verifier 或 OperatorResponse。
- 新策略研究、Memory/Skill 自主学习、paper/Testnet/live/order/capital mutation。
- 在浏览器保存 provider key、交易凭证、private reasoning 或无限原始工具响应。

## Done Means

1. Web 连续执行“比较两个策略”与“后者最大回撤多少”，第二 Turn 使用服务端持久化实体解析正确策略。
2. 页面在 tool、evidence 和 answer streaming 三个位置分别断开后，按 cursor 恢复且 Item 不丢失、不重复。
3. 每个 Turn 恰好显示一个 terminal event；网络 EOF 本身不能被渲染为完成。
4. 相同 `client_message_id` 和 payload 重试返回同一 Turn；相同 key 不同 payload 显示 409 语义。
5. Web 不发送 `prior_turns`，不把浏览器缓存作为会话真相源。
6. Web 与 Remote CLI 对相同 Thread projection 的目标、Evidence、unknown 和终态解释一致。
7. LAB 精确行情、数据缺口和主网阻断场景保持正确，事实回答都有 source/Evidence ref。
8. Web canary 前后 `agent_runs` 与 `agent_tasks` 新增行均为 0。
9. 历史 legacy 页面仍可读取旧记录，但不能从 Web 自然语言入口创建新 legacy run/task。
10. 本 Sprint 不新增 paper、Testnet、live、订单、资金或凭证权限。

## Verification

实现时至少运行：

```bash
npm exec --yes pnpm@10 -- -C frontend test
npm exec --yes pnpm@10 -- -C frontend lint
npm exec --yes pnpm@10 -- -C frontend build
uv run pytest tests/test_thread_turn_api.py tests/test_thread_turn_replay.py -q
uv run pytest tests/test_web_thread_turn_contract.py -q
./scripts/check.sh
git diff --check
```

生产只读 canary 必须覆盖真实两轮指代、LAB、主网阻断、SSE 中断恢复、浏览器刷新恢复和 legacy row-count
前后对比。不得保存生产原始工具载荷、账户敏感信息或凭证。

## Handoff

Sprint 123 把 Mission 生命周期的所有 projection 更新改为 versioned event + deterministic reducer，并建立
独立 completion proof。Sprint 122 完成前，不把自主策略研究、paper 自动化或 live 权限接到 Web 协议。
