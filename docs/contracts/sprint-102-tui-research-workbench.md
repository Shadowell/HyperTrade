# Sprint 102 - TUI Research Workbench

> 状态：Active；Sprint 96–101 已完成验收，2026-07-15 开始实施。

## Goal

增加可选的 Textual TUI，让操作员在终端中查看 Session、后台 Task、研究图、Evidence、
实验、验证、预算和审批，并安全执行 pause/resume/cancel/retry。

## In Scope

- 可选 `tui` dependency extra 和 `ht tui` 命令。
- Sessions/Tasks、Graph/Timeline、Evidence/Approval、Report/Experiment/Validation 面板。
- 多行输入、任务筛选、快捷键、modal confirmation 和窄终端适配。
- REST snapshot + cursor SSE 同步、断线重连和最终状态 refresh。
- 复用现有 Rich 主题、AgentClient protocol、认证和 API。

## Out of Scope

- 替换 `ht chat`、plain script output 或 Web Harness。
- TUI 直接访问数据库、ToolRegistry、BitPro 或业务 service。
- 在客户端实现状态转换、审批、预算或风险判断。
- 单键执行任何危险 mutation。

## Deliverables

- Textual app、screens、widgets、view models 和 API/SSE client。
- `ht tui` parser/config/login integration。
- headless TUI tests、fake SSE tests 和 CLI 回归测试。
- 用户手册、快捷键、故障恢复和部署说明。

## Implementation Plan

1. 在 optional dependency 中加入固定版本 Textual，保持基础 CLI 不强制安装。
2. 扩展 AgentClient protocol 覆盖 Session/Task/Event/Evidence/control API。
3. 实现 store/view model，先加载 REST snapshot 再订阅 cursor SSE。
4. 构建 Sessions/Tasks 导航和任务状态/预算指标。
5. 构建 Research Graph/Timeline 与 node retry/error/checkpoint 详情。
6. 构建 Evidence、Experiment、Validation 和 Approval detail panels。
7. 实现多行 prompt、新 Task、pause/resume/cancel/retry/branch modal。
8. 实现 auth failure、API deploy、SSE disconnect、unknown event 和 reconnect UI。
9. 完成 80/120/160 列布局和非颜色/无鼠标键盘路径。
10. 增加 headless snapshot、交互和现有 CLI 回归测试。

## Done Means

- 操作员可以在一个终端工作台定位运行、失败、暂停、审批等待和预算耗尽任务。
- TUI 断线重连后不丢事件、不重复事件，并重新读取最终 Task 状态。
- 所有 mutation 经 API auth、reason、idempotency 和服务器状态机。
- 未安装 `tui` extra 时基础 `ht` 命令可用并给出清晰安装提示。
- `ht chat`、plain renderer、脚本和 Web Harness 无回归。

## Verification

```bash
uv run pytest tests/test_tui_app.py tests/test_tui_event_recovery.py -q
uv run pytest tests/test_cli.py tests/test_api.py -q
./scripts/check.sh
```

Manual/QA：

- 远程 API 部署重启期间保持 TUI 进程，确认恢复后续事件。
- 在窄终端和无鼠标环境完成任务查看、暂停和恢复。
- 验证 dangerous action modal 必须填写原因且服务器拒绝非法转换。

## Risks / Notes

- TUI 只是 surface；任何业务逻辑进入 UI 都视为架构回归。
- Textual 版本需固定并在 Linux/macOS 终端 smoke。
- 大量事件需要虚拟列表/分页，不能一次加载全部历史。

## Handoff

- 下一步：Sprint 103 让后台触发的 bounded Task 出现在同一 TUI/API 工作流。
