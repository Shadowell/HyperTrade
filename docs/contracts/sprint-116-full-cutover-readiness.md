# Sprint 116 - Full Cutover, Professional UX & Readiness

> 状态：Completed locally; Gate M production canary remains pending. Sprint 115 Gate L 的本地安全合同已关闭。

## Goal

让同一个 Mission 在 REST、SSE、CLI 和 Web operator surface 上具有一致的可恢复工作流投影，
并建立最后的 readiness gate。用户可以查看计划、步骤、预算、证据和事件，在安全点 pause、
resume、cancel 或 steer；系统不以模型文字宣称完成，不放宽 paper/live/order 权限。

## In scope

- `/harness/missions` Mission workspace：列表、详情、Plan/Step/Artifact/Event/Budget panels。
- Mission create/run/control/steer 与 cursor event replay；断线时 REST fallback，不能丢失审计事件。
- 复用 Agent Flight Recorder 的 telemetry/card 视觉，不再维护第二套 Mission 状态机。
- 长任务 deterministic readiness scenarios：provider/source/schema/lease/steer 故障、恢复、预算和安全门禁。
- Sprint 115 rootless container adapter deployment contract；未配置时生产继续 fail-closed。
- 旧 Mission 写路径审计、feature flag/canary、README/architecture/progress/QA 更新。

## Out of scope

- 自动 BitPro strategy import、paper/live/order/capital mutation。
- 删除历史只读 AgentTask/AgentRun 查询前的兼容迁移。
- 引入第二套队列、Redis/Celery/Temporal 或自由对话群。

## Done means

- Web/CLI/API 对同一 Mission 的 status、plan version、step state、usage、artifact refs 和 event cursor 一致。
- create/run/control/steer 具备鉴权、理由、幂等和审计；SSE 支持 `after`/`Last-Event-ID` replay，
  断线不会产生第二次 step dispatch。
- 至少 20 个 deterministic readiness cases 覆盖预算、恢复、stale source、provider/MCP failure、
  DB lease、schema mismatch、steer 和 approval bypass；unsafe dispatch 与 false completed 为 0。
- 生产 `AGENT_STRATEGY_SANDBOX_ENABLED` 默认关闭；无 rootless container adapter 时 HTTP 503，
  不能执行宿主 subprocess。
- README、技术架构、QA、progress 和 active contract 记录实际验证，不声称未做的部署/截图/生产 canary。

## Verification

```bash
uv run pytest tests/test_agent_missions.py tests/test_task_events.py tests/test_sandbox_isolation.py -q
uv run pytest tests/test_professional_agent_readiness.py -q
./scripts/check.sh
git diff --check
```

## Handoff

Gate M 通过后，旧 AgentKernel/legacy Mission write callers 才能按 deletion budget 删除；历史
查询保留只读 adapter。若容器 canary、长任务恢复或安全 gate 任一失败，feature flags 保持关闭，
并把失败证据留在 QA 报告中。
