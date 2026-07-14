# Sprint 104 - Governed Memory and Skill Lifecycle

> 状态：Active；Sprint 97、101、103 已完成验收，2026-07-15 开始实施。

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
