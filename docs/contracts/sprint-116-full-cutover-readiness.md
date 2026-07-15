# Sprint 116 - Full Cutover, Professional UX & Readiness

> 状态：Active — completion audit reopened on 2026-07-16. Sprint 115 Gate L 的本地安全合同已关闭，
> 但默认 chat/CLI/TUI/worker 尚未完成 Mission Runtime 切换，Gate M 不能宣称完成。

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
- Sprint 115 rootless container adapter deployment contract；未配置时生产继续 fail-closed。
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
  隔离评测必须明确报告 `not_supported`，不得计为通过。
- 生产 `AGENT_STRATEGY_SANDBOX_ENABLED` 默认关闭；无 rootless container adapter 时 HTTP 503，
  不能执行宿主 subprocess。
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

Gate M 通过后，旧 AgentKernel/legacy Mission write callers 才能按 deletion budget 删除；历史
查询保留只读 adapter。若容器 canary、长任务恢复或安全 gate 任一失败，feature flags 保持关闭，
并把失败证据留在 QA 报告中。
