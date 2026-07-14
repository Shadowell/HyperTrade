# Sprint 104 - Governed Memory and Skill Lifecycle

> 状态：Completed；2026-07-15 本地与生产验收通过。

## Goal

将长期 Memory 和可复用 Skill 从“直接写入内容”升级为带来源、冲突、过期、提案、评测、
人工批准、发布和回滚的治理生命周期。

## In Scope

- `MemoryAssertionV1`、冲突/支持/supersede/expire 关系。
- `SkillDefinitionV1`、proposal、evaluation、approval、release、rollback。
- Skill V1 支持 prompt/tool/schema/report procedure，不支持任意代码执行。
- isolated eval regression、static policy check 和 release hash。
- API/CLI/TUI/Web review surfaces。

## Out of Scope

- Agent 自行发布 Skill、执行未审查 shell/Python 或添加网络 endpoint。
- 自动解决有争议的 Memory claim。
- 让 Memory 替代 BitPro/tool Evidence。
- 从互联网自动安装并启用任意第三方 Skill。

## Deliverables

- MemoryAssertion 和 Skill lifecycle models/services/migrations。
- proposal diff、static checks、isolated eval、approval 和 rollback 服务。
- approved skill loader 与 ToolRegistry/role prompt integration。
- review UI、审计、评测和隐私测试。

## Implementation Plan

1. 定义结构化 Memory assertion、来源 evidence、有效期和冲突关系。
2. 将现有 MemoryItem 作为存储/显示兼容层，新增 assertion read/write policy。
3. 定义 Skill 允许内容、禁止字段、版本、hash 和 active pointer。
4. 创建 proposal/evaluation/approval/release 表和状态机。
5. 实现 canonical diff 和 static policy check，拒绝 script/secret/network adapter。
6. 将 proposed Skill 安装到 isolated eval 临时目录运行 golden/regression。
7. 管理员查看 diff、评测和权限后批准；发布 immutable version。
8. RoleExecutor 只加载 active approved Skill metadata/template。
9. 实现 rollback，只切 active pointer，不删除历史 release。
10. 完成冲突、过期、恶意 Skill、评测失败、审批和回滚测试。

## Done Means

- Memory 冲突和过期可查询，系统不会静默选边或使用失效 assertion。
- Agent 只能创建 proposal，不能直接改变 active Skill。
- 未通过 static/eval/admin approval 的 Skill 不会进入任何生产 prompt/toolset。
- release/rollback 保留完整 hash、diff、评测、操作者、原因和时间。
- Skill/Memory 内容不能扩大 ToolRegistry 或 paper/live 权限。

## Verification

```bash
uv run pytest tests/test_memory_assertions.py tests/test_skill_lifecycle.py -q
uv run pytest tests/test_agent_research_evals.py tests/test_agent_tool_policy.py -q
./scripts/check.sh
```

## Risks / Notes

- Skill V1 刻意不运行代码；若未来需要脚本，必须单独设计容器沙箱和供应链审查。
- Memory confidence/importance 不能覆盖来源过期或冲突状态。
- proposal 内容和 eval artifact 继续遵守 prompt/report 隐私边界。

## Handoff

- 下一步：Sprint 105 使用受治理 evidence/memory 形成组合级策略生命周期审阅。

## Implementation Record

- Alembic `0017_memory_skills` 新增 Assertion、relation、review、Skill proposal、
  evaluation、approval、release 和 active pointer 八张表；PostgreSQL 已通过完整
  upgrade/downgrade/upgrade。
- `MemoryAssertionService` 强制 Evidence V2 来源、人工 review、冲突/替代/过期状态和
  fail-closed 检索；现有 `MemoryItem` 仅作为兼容投影，来源失效会在普通检索前禁用。
- `SkillLifecycleService` 只接受无代码 definition，静态阻断脚本、网络、secret、写工具和
  role 权限扩张。隔离评测使用 HMAC 证明绑定 proposal hash、suite、baseline、计数和 artifact；
  未配置验签密钥、证明被篡改或缺少人工批准时均不能发布。
- 发布使用 immutable release/hash/version 与 active pointer；PostgreSQL row/advisory locks
  串行化 review/release，rollback 只切换 pointer 并保留历史。
- `ApprovedSkillLoader` 仅向匹配角色 prompt 注入 hash/schema/tool-policy 均有效的 active
  metadata/template，不注册工具、不执行代码、不扩大 paper/live 权限。
- 管理员 API、CLI `/assertions`/`/skills`、TUI Governance tab 和 Web Memory 治理队列共用
  同一服务端状态机，所有决策要求 reason 和 idempotency。

## Local Acceptance

- `./scripts/check.sh`：前端 lint、8 tests、build；Ruff；mypy 138 source files；
  464 Python tests。
- PostgreSQL migration：`0017` upgrade → `0016` downgrade → `0017` upgrade，8 表存在。
- 聚焦 Assertion/Skill/API/CLI/TUI/role-loader 测试通过；伪造 attestation、过期来源、
  冲突 assertion、恶意 Skill、未评测发布与 hash tamper 均 fail closed。

## Production Acceptance

- Commit `d4d43bb` 在 workflow `29363666735` 部署成功，记录 SHA 完全一致。
- API/Worker 正常，最近部署日志无 error/traceback；PostgreSQL head 为
  `0017_memory_skills`，8/8 治理表存在。
- 管理员读取 Assertion、proposal、release 均 HTTP 200 且为空，没有生产内容被激活。
- 生产共享 attestation secret 尚未配置；伪造证明导入返回 HTTP 409，验证默认 fail closed。
