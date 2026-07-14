# Sprint 96 - Agent Sessions and Task Control

> 状态：Completed，2026-07-14 完成实现、全量回归、生产部署与远程验收。

## Goal

建立统一、持久、可恢复的 Agent Session 与 Task 控制面，让 CLI/API 任务支持
pause、resume、cancel、retry、branch、checkpoint 和 SSE cursor 恢复，同时保持现有
AgentRun、ResearchJob 和命令行为兼容。

## In Scope

- 新增 `AgentSession`、`AgentTask`、`TaskNodeRun`、`TaskCheckpoint`、`TaskEvent` 表。
- 新增状态转换、预算、lease、heartbeat、checkpoint 和 event sequence 服务。
- 将 `ht ask`、`ht chat` 和现有 Agent API 包装为兼容 Task，但不改变报告结果。
- 新增 Session/Task REST、控制 API 和 cursor-based SSE。
- worker 支持 durable task 领取与恢复；PostgreSQL 使用 skip-locked lease。
- 新增 `/sessions`、`/tasks`、`/task <id>` CLI 查询和控制命令。

## Out of Scope

- 多 Agent 角色图、Evidence V2、TUI 和后台触发器。
- 自动恢复无法确认结果的非幂等外部写动作。
- 把旧 AgentRun 伪造成完整历史对话。
- 修改 BitPro、paper 或 live 权限。

## Deliverables

- Alembic migration 和 SQLAlchemy models/indexes。
- `AgentSessionService`、`AgentTaskService`、`TaskEventService`、`TaskExecutor`。
- Task API、SSE 和 CLI commands。
- legacy AgentRun/ResearchJob adapter。
- 状态机、lease、恢复、idempotency、API/CLI 回归测试。
- 更新 API、CLI 和 Agent Research OS 技术文档。

## Implementation Plan

1. 先修复 Sprint 95 暴露的 Provider timeout 裸 HTTP 500：统一映射为可审计、
   可重试的结构化 Task 错误，再定义状态枚举、合法转换表和预算 schema。
2. 添加数据库表、唯一约束、sequence 索引、lease/heartbeat 字段与 migration 测试。
3. 实现事务性 Task 创建：Task 与首个 Event 必须同事务提交。
4. 实现 Task transition/control；所有 mutation 要求 reason 和 idempotency key。
5. 实现 checkpoint 写入、state hash、resume token 和外部写 reconciliation 标记。
6. 扩展 worker：领取、heartbeat、lease takeover、pause/cancel 安全点。
7. 增加 REST/SSE；支持 `Last-Event-ID` 和 `after` cursor。
8. 接入现有 AgentKernel；one-shot 请求自动创建 ephemeral Session/Task。
9. 增加 CLI 查询/控制命令并保持 plain/Rich/script 输出兼容。
10. 完成重启、断线、重复请求、非法转换和现有功能回归测试。

## Done Means

- API 进程或 worker 重启后，Task 可以从最后成功 checkpoint 恢复。
- 重复 idempotency key 不创建第二个 Task 或重复外部写动作。
- pause/cancel/retry/branch 均留下操作者、原因、事件和状态历史。
- SSE 断线后从 cursor 恢复，客户端不会重复显示已提交事件。
- 现有 `ht ask`、`ht chat`、`/runs`、`/run` 和 Harness 继续工作。
- 旧 Run 明确标记 legacy，不伪造缺失的 Session 历史。

## Verification

```bash
uv run pytest tests/test_agent_sessions.py tests/test_agent_tasks.py tests/test_task_events.py -q
uv run pytest tests/test_cli.py tests/test_api.py -q
./scripts/check.sh
```

Manual/QA：

- 启动长任务，断开 SSE 后用最后 sequence 重连。
- 执行中请求 pause，重启 worker，再 resume 并确认未重复已完成节点。
- 使用相同 idempotency key 重发创建请求，确认返回同一 Task。

## Risks / Notes

- SQLite 不提供生产级 skip-locked 并发，开发模式限制单 worker。
- BitPro 同步调用中断时只能记录结果未知并恢复前 reconcile，不能谎报取消成功。
- Provider timeout 必须进入 `retry_wait` 或结构化 `failed`，不得以未处理异常中断
  SSE、整批评测或返回裸 HTTP 500。
- Task/Event payload 必须使用安全投影，禁止保存 credential 或 private reasoning。

## Handoff

- 下一步：Sprint 97 定义所有研究角色必须使用的 Evidence V2 合同。

## Implementation Record

- 实现提交：`65c8a41`；生产部署工作流：`29338187375`，状态 success。
- 聚焦回归 `101 passed`；`./scripts/check.sh` 全部通过，Python 测试
  `350 passed`。
- 生产真实运行 `run_e2c36d58611f4c49ba5f` 被持久化为
  `ses_dd5306ed19374f1b94b2` / `task_dd509a0e4b924187bafa`，最终状态
  `completed`，生成 checkpoint `tcp_0698fd674ca0437fb36b` 和 25 条连续事件。
- 生产远程 CLI 的 `/sessions`、`/tasks`、`/task` 均读取同一持久 Task 投影；
  Event API 使用 `after=0` 和 `after=3` 分别返回 sequence `1..3`、`4..6`，
  验证 cursor 无重复恢复。
- 生产健康检查返回 `{"status":"ok","service":"hypertrade-api"}`；API 成功读取
  Session/Task/Checkpoint/Event，确认 PostgreSQL migration 已生效。
