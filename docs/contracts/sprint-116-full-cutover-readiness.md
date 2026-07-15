# Sprint 116 - Full Cutover, Professional UX & Readiness

> 状态：Completed — 2026-07-16。Mission-first API/CLI/TUI/worker 已完成生产切换；隔离评测
> 20/24 supported-case 通过（4 个多轮场景明确为 `not_supported`），digest-bound sandbox 与
> worker/SSE/100% canary 均已在生产验证。没有开启任何 paper、live、order 或 capital mutation。

## Goal

让同一个 Mission 在 REST、SSE、CLI 和 Web operator surface 上具有一致的可恢复工作流投影，
并建立最后的 readiness gate。用户可以查看计划、步骤、预算、证据和事件，在安全点 pause、
resume、cancel 或 steer；系统不以模型文字宣称完成，不放宽 paper/live/order 权限。

## In scope

- `/harness/missions` Mission workspace：列表、详情、Plan/Step/Artifact/Event/Budget panels。
- Mission create/run/control/steer 与 cursor event replay；断线时 REST fallback，不能丢失审计事件。
- 默认 chat API 的稳定 percentage canary：同一 idempotency key 必须始终命中同一 runtime；命中
  Mission 后不得写入 `AgentTask` 或 `AgentRun`，响应从 Mission/Plan/Attempt/Event facts 投影。
- 复用 Agent Flight Recorder 的 telemetry/card 视觉，不再维护第二套 Mission 状态机。
- 长任务 deterministic readiness scenarios：provider/source/schema/lease/steer 故障、恢复、预算和安全门禁。
- `OperatorResponseV1`：默认回答只投影结论、置信度、已验证证据、明确缺口和安全下一步；运行、
  工具和审批状态作为独立审计/事件面，不能混入默认结论。
- 隔离 `operator_answer_golden_v1`：覆盖市场、策略、组合、执行、上下文和交付场景；真实运行产物
  只能保留 case 级通过/失败、长度和聚合计数，不能保存提示、回答正文、工具参数、原始结果或凭据。
- Sprint 115 digest-bound isolated sandbox service deployment contract；未配置或 IPC 不可用时生产继续
  fail-closed。
- 旧 Mission 写路径审计、feature flag/canary、README/architecture/progress/QA 更新。

## Out of scope

- 自动 BitPro strategy import、paper/live/order/capital mutation。
- 删除历史只读 AgentTask/AgentRun 查询前的兼容迁移。
- 引入第二套队列、Redis/Celery/Temporal 或自由对话群。

## Done means

- Web/CLI/API 对同一 Mission 的 status、plan version、step state、usage、artifact refs 和 event cursor 一致。
- `MISSION_RUNTIME_ENABLED=true` 且 `MISSION_RUNTIME_CANARY_PERCENT=100` 时，默认 API chat 只写
  Mission 账本；重复同一 idempotency key 返回同一 Mission，内容不一致返回冲突。
- create/run/control/steer 具备鉴权、理由、幂等和审计；SSE 支持 `after`/`Last-Event-ID` replay，
  断线不会产生第二次 step dispatch。
- 至少 20 个 deterministic readiness cases 覆盖预算、恢复、stale source、provider/MCP failure、
  DB lease、schema mismatch、steer 和 approval bypass；unsafe dispatch 与 false completed 为 0。
- 默认 Mission 回答不显示 Mission id、plan version、工具数或步骤清单；每个可见事实必须绑定 source/
  artifact ref，缺失数据时必须拒绝补全并给出一个具体的安全下一步。
- `operator_answer_golden_v1` 至少 24 个场景；多轮指代和公开 answer/evidence stream 尚未支持时，
  隔离评测必须明确报告 `not_supported`，不得计为通过；无 supported case 失败时可返回
  `complete_with_declared_gaps`，但 `passed_count` 不得包含这些 case。
- mainnet execution、unapproved/Testnet execution、过高杠杆和明确 stale input 在 Plan 前进入
  `blocked`、`waiting_approval` 或 `waiting_input`；不得调用 provider、connector 或写能力。
- `evaluation_case_id` 只允许物理隔离目标且 `HYPERTRADE_OPERATOR_EVAL_FIXTURES_ENABLED=true`；生产
  必须拒绝该入口，fixture 不得访问 provider、BitPro 或交易能力。
- Catalog 新增的 strategy/backtest、paper portfolio 和 Testnet intent summary 必须保持 `read` /
  `side_effect=none`，仅在隔离评测环境 idempotent seed 的合成事实；不得用 prompt 或模型文字伪造
  可见证据。
- 源码默认 `AGENT_STRATEGY_SANDBOX_ENABLED=false`；生产仅在 digest-bound isolated sandbox
  canary 通过后显式启用。无 digest-bound service 时仍返回 HTTP 503，不能执行宿主或 API subprocess。
- README、技术架构、QA、progress 和 active contract 记录实际验证，不声称未做的部署/截图/生产 canary。

## Verification

```bash
uv run pytest tests/test_agent_missions.py tests/test_task_events.py tests/test_sandbox_isolation.py -q
uv run pytest tests/test_professional_agent_readiness.py -q
uv run pytest tests/test_operator_answer_evals.py tests/test_operator_response.py -q
# Requires a version-matched isolated Mission-canary target; never production.
HYPERTRADE_EVAL_TARGET=isolated HYPERTRADE_EVAL_BASE_URL=http://127.0.0.1:4334 \
  ./scripts/run_operator_answer_eval.sh
./scripts/check.sh
git diff --check
```

## Handoff

Gate M 已通过：生产 `MISSION_RUNTIME_CANARY_PERCENT=100`，新的 chat/worker 写入均进入 Mission
账本；`AgentTask`/ResearchGraph 写入口返回 HTTP 410，历史查询保持只读。后续删除仅限没有
生产调用者的 legacy implementation budget，不能删除历史审计读取或放宽交易权限。

## User-directed desktop client

The separately requested desktop floating client is governed by
`docs/contracts/user-directed-desktop-floating-bot.md`. It consumes the same public Mission stream
and adds no runtime truth source or execution permission. Its local completion does not close Gate M.
