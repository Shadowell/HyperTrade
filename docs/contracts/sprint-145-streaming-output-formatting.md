# Sprint Contract: Streaming Output Formatting (TUI/输出优化)

## Sprint Name

`streaming-output-formatting`

## Goal

修复 sprint-144 引入的显示回归：流式回答目前是裸文本（无 markdown 渲染、
无宽度自适应），且流式完成后跳过 rich 渲染，用户主要看到裸 markdown。
升级为 rich Live 增量渲染 + 结构化收尾 footer + 流式期间工具事件可见。

## In Scope

- `_LiveMarkdownStreamer`（cli.py）：
  - rich 可用 + TTY + 未设 `HYPERTRADE_STREAM_RENDERER=plain` 时，用
    `rich.live.Live` + `Markdown` 节流增量重渲染（时间/字符双阈值）。
  - 流式期间工具事件以紧凑单行经 Live console 打印在渲染区上方。
  - 非 TTY/管道/plain 模式保持裸文本直写（现有行为）。
- 收尾 footer 结构化：run id + 时长 + token + 工具数 + 压缩次数（取自
  final_run.observability），替代当前只有 run id 的一行。
- 非 rich 环境行为逐字节不变。

## Out of Scope

- Textual TUI 任务台的渲染改造。
- final 渲染路径（`_render_rich_run`）重构——已达标。
- 工具输出的增量流式。

## Deliverables

- `cli.py`：streamer + footer builder + render_run_stream 接线。
- `tests/test_cli_stream_formatting.py`：plain 模式直通、缓冲阈值、footer
  内容、工具行格式、rich 缺失回退。

## Done Means

- TTY 下流式回答以格式化 markdown 实时渲染；工具事件流式期间可见。
- 管道/plain 模式与 rich 缺失环境输出与现状一致。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_cli_stream_formatting.py tests/test_cli.py
./scripts/check.sh
```

## Risks / Notes

- Live 重渲染对超长报告有刷新成本；节流（refresh_per_second=4）+ 报告典型
  长度 <4k 字符下可接受。
- rich 为既有依赖（lazy import 已存在），无新增依赖。

## Handoff

- Next likely step: P2 深度项或 ARC codegen × workspace 融合。
