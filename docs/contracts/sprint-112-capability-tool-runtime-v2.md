# Sprint 112 - Capability and Tool Runtime V2

> 状态：Implemented / production acceptance pending；Sprint 111 Gate I 已关闭。

## Goal

让 Mission Planner 只能引用经过审核、版本化、可健康检查的 Capability，并让每次执行产生
schema-valid、来源绑定、错误分类明确的 ToolObservation。自动发现只能形成 pending proposal，
不得扩大生产 allowlist、approval 或交易权限。

## In Scope

- strict CapabilityDefinitionV1、CapabilitySnapshotV1、CapabilityProposalV1、ToolRequestV2、
  ToolObservationV2 和 error taxonomy。
- Capability Catalog port、内存/SQLAlchemy adapter、migration `0024_agent_capabilities`。
- 从现有 ToolRegistry 生成 reviewed snapshot；contract/policy hash、read/write/destructive、
  approval、idempotency、timeout、health、freshness 和 source owner 全部显式。
- MCP/OpenAPI discovery proposal ingestion；默认 `pending_review`，只有管理员明确 approve/reject。
- Planner PlanStep 对 catalog capability id/version 验证；未知、stale、unhealthy、scope 不匹配、
  approval 不满足均在 pre-dispatch 失败关闭。
- GovernedToolExecutor：输入/输出 JSON Schema、Pydantic observation、policy hash、catalog version、
  idempotency binding、timeout 和 bounded result preview。
- deterministic error recovery matrix 与 per-capability circuit state；timeout/rate/source/contract/
  permission/unsafe 明确区分，禁止模型把文本错误当成功。
- 首批只读 adapters：runtime objective inspection、market ticker/summary、RAG search、Memory search。
- Capability list/proposal/review/health API 和 Mission 投影中的 capability/observation refs。
- 删除 foundation hard-coded allowlist 和重复 planner tool-name mapping 的新 Runtime 分支。

## Out of Scope

- Sprint 113 Context Pack、Artifact Index、自动 compaction。
- Sprint 114 Multi-Agent role selection/concurrency。
- Sprint 115 shell、代码生成、Docker sandbox 或 BitPro import。
- 自动启用 discovery、自动 approval、paper/live/order/capital 权限变化。
- 替换现有旧 AgentKernel ToolRegistry 的所有调用者；本 Sprint 只切新 Runtime。

## Done Means

- 100% Mission tool calls绑定 capability id/version、contract hash、policy hash 和 observation id。
- 未 reviewed 或 stale/unhealthy capability 在执行前被拒绝，handler 调用次数为零。
- 输入/输出 schema mismatch 产生 `contract_mismatch`，一次 repair 后仍失败即终止或 replan。
- transport timeout/rate/source errors按固定矩阵 retry/replan/circuit-open，不无限循环。
- write/destructive/approval capability 不能进入 read-only Mission。
- discovery proposal 不出现在 active catalog；review decision append-only、幂等且管理员限定。
- API、数据库、event stream 不保存凭证、raw 大结果、private reasoning。
- 新 Runtime 不再依赖 foundation hard-coded allowlist。
- 全仓检查、migration 往返、production flag-off 和 read-only canary 通过。

## Verification

```bash
uv run pytest tests/test_capability_catalog.py tests/test_tool_runtime_v2.py -q
uv run pytest tests/test_agent_missions.py tests/test_tool_registry.py tests/test_bitpro_mcp_adapter.py -q
./scripts/check.sh
```

Required scenarios: reviewed success, pending denial, version/hash mismatch, stale/unhealthy denial,
input/output mismatch, timeout retry, rate-limit circuit open/half-open, idempotent replay, approval
denial, write-scope denial, result truncation, secret redaction and discovery proposal review.

## Handoff

Gate J1 通过后才激活 Sprint 113。Sprint 113 可以消费 Capability/Observation refs，但不能绕过
catalog、policy、schema、circuit、idempotency 或 approval 门禁。
