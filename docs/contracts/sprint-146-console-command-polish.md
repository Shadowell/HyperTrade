# Sprint Contract: Interactive Console Preset Command Polish (TUI 输出优化②)

## Sprint Name

`console-command-polish`

## Goal

优化交互页面的预置命令展示：banner 与 `/help` 目前是手工空格对齐 + 中英混排 +
30+ 条平铺无分组，视觉粗糙且难检索。重构为 rich 网格精确对齐、统一中文描述、
按功能分组着色的专业布局；非 TTY 环境保留纯文本回退。

## In Scope

- Banner 重构（rich Panel + grid）：
  - 状态区（MODEL/RUNTIME/EXECUTION/MAINNET）网格对齐。
  - 主线快捷与运维控制统一中文描述、命令列等宽着色。
  - 非 TTY 回退现有 ANSI 文本版（描述同步中文化）。
- `/help` 分组渲染：按「主线 / 行情 / 研究与证据 / 任务与运行 / 记忆与技能 /
  模拟盘与实盘 / 配置与诊断」七组，rich Table 两列对齐 + 组标题着色；
  非 TTY 回退现有平铺。
- 同步更新 banner 相关测试断言。

## Out of Scope

- 候选补全列表（`render_slash_command_candidates`）微调不动。
- Textual TUI 任务台。
- 新增/删除 slash 命令。

## Deliverables

- `cli.py`：`_HELP_SECTIONS` 分组、`render_slash_help` rich 分支、
  `render_welcome_banner` rich 分支（旧版保留为回退）。
- 测试更新：banner 中文断言 + help 分组断言 + 非 TTY 回退断言。

## Done Means

- TTY 下 banner 与 /help 为网格对齐、分组着色的中文布局；管道环境输出纯文本。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_cli.py tests/test_cli_stream_formatting.py
./scripts/check.sh
```

## Risks / Notes

- rich 输出到非 TTY 会带 ANSI 转义：rich 分支以 `isatty` 严格门控。

## Handoff

- Next likely step: Textual 任务台与 chat 融合，或回主线 P2。
