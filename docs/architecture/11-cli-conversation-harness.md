# 11 CLI Conversation Harness / CLI 对话 Harness

## English

The CLI is a developer harness with two runtime modes:

- Local standalone mode: `hypertrade`, `hypertrade chat`, or `hypertrade ask <prompt>` load `Settings`, connect to the configured database, create an `AgentKernel`, and persist runs/traces through the same backend services.
- Remote API mode: `hypertrade --remote <url>` authenticates with `/api/auth/login`, prefers `POST /api/agent/runs/stream` for Server-Sent Events, and falls back to `/api/agent/runs` style full-run rendering when streaming is unavailable.

Configuration is environment-based:

- `hypertrade /login` or `ht /login` saves a remote API URL, username, and
  password to `~/.hypertrade/client.env` with local-only permissions.
- `HYPERTRADE_API_URL` selects the API endpoint and makes remote mode the default unless `--local` is passed.
- `HYPERTRADE_USERNAME` and `HYPERTRADE_PASSWORD` provide admin credentials.
- `HYPERTRADE_TIMEOUT_SECONDS` controls HTTP timeout.
Saved client config is read before the runtime is selected, and explicit
environment variables override the saved values for automation.

The production host wrapper installed at `/usr/local/bin/hypertrade` runs a
short-lived client container with `HYPERTRADE_API_URL=http://api:3334` by
default. This avoids attaching the operator's terminal to the long-running
`hypertrade-api` service container. During a deployment, the API container can
still restart and interrupt the current API request, but the terminal CLI
process is not killed by `docker compose up -d api worker`.

Interactive chat also supports slash commands for harness inspection without starting a new Agent run.
`/help` renders every command with a short purpose statement, and `/tools` renders each
registered Agent tool with category, approval marker, and registry description:

- `/help`, `/status`, `/model`, `/providers`
- `/tools`, `/runs`, `/memory`
- `/strategy`, `/backtests`
- `/research <prompt>`, `/backtest`, `/backtest latest`

Local mode reads these from `ToolRegistry`, `AgentRun`, `MemoryService`, `StrategyResearchService`, and `BacktestService`. Remote mode calls the matching FastAPI list endpoints and `/api/harness/overview` for status/model summaries.

Workflow shortcuts call `StrategyResearchService.create()` and `BacktestService.run()` locally, or `POST /api/strategy/research` and `POST /api/backtests` remotely.

Real TTY chat sessions load readline-backed command history from
`~/.hypertrade/history`. Valid prompts and slash commands are added to history
so arrow keys recall prior requests; non-TTY/script runs keep plain input
behavior and do not mutate terminal history.

Run streaming uses a small stable event shape:

- `run_started`
- `tool_started`
- `tool_completed`
- `run_completed`
- `run_failed`
- `final`

The CLI renders these as progress lines before printing the final stored run report. This is
progress streaming, not token-by-token model streaming.
When stdout is an interactive terminal, the CLI also shows a small `Thought` / `Thinking`
status block while waiting for planner or tool events. The block is cleared before durable
status lines and the final report are printed, and non-TTY output stays plain for scripts.
`HYPERTRADE_THINKING_ANIMATION=1` forces the block for smoke tests, while `0` disables it.

Report rendering prefers structured JSON/trace payloads when available. If a run only has
Markdown, Rich-capable interactive output renders headings, lists, emphasis, and tables instead
of printing raw Markdown source. `HYPERTRADE_RENDERER=plain` keeps the raw Markdown fallback for
automation.
Rich run output folds low-signal trace rows by default: graph runtime nodes, BitPro
capability/health preflight rows, and nested BitPro subcalls are summarized instead of printed as
a long table. Business-level tool calls remain visible with an aggregated call count. Operators can
set `HYPERTRADE_TRACE=full` to print the complete trace table during audits or debugging.

This keeps Provider configuration, Tool Call policy, RAG, Memory, approval gates, and trace persistence in one runtime boundary. The terminal becomes another harness surface alongside `/harness`.

## 中文

CLI 是开发者 Harness，支持两种运行模式：

- 本地 standalone 模式：`hypertrade`、`hypertrade chat` 或 `hypertrade ask <prompt>` 会加载 `Settings`，连接配置的数据库，创建 `AgentKernel`，并通过同一套后端服务持久化 run/trace。
- 远程 API 模式：`hypertrade --remote <url>` 会调用 `/api/auth/login` 登录，优先通过
  `POST /api/agent/runs/stream` 消费 Server-Sent Events；如果流式不可用，再回退到完整 run
  输出。

配置通过环境变量完成：

- `hypertrade /login` 或 `ht /login` 会把远程 API URL、用户名和密码保存到
  `~/.hypertrade/client.env`，并设置为本机私有权限。
- `HYPERTRADE_API_URL` 选择 API 地址，并让远程模式成为默认；传 `--local` 可以强制本地模式。
- `HYPERTRADE_USERNAME` 与 `HYPERTRADE_PASSWORD` 提供管理员凭据。
- `HYPERTRADE_TIMEOUT_SECONDS` 控制 HTTP 超时。
CLI 在选择本地/远程运行模式前会读取保存的本机配置；显式环境变量仍会覆盖保存值，方便自动化。

生产宿主机上的 `/usr/local/bin/hypertrade` wrapper 会启动一个短生命周期的 CLI client
容器，并默认设置 `HYPERTRADE_API_URL=http://api:3334`。它不再 attach 到长期运行的
`hypertrade-api` 服务容器，所以部署执行 `docker compose up -d api worker` 替换 API
容器时，不会直接杀掉操作员终端里的 CLI 进程。部署期间当前 API 请求仍可能中断，但交互式
CLI 会显示可重试的远程 API 连接提示。

交互式 chat 还支持斜杠命令，用于查看 Harness 状态而无需发起新的 Agent run。`/help`
会为每条命令显示用途说明，`/tools` 会为每个 Agent 工具显示 category、approval 标记和
registry 描述：

- `/help`、`/status`、`/model`、`/providers`
- `/tools`、`/runs`、`/memory`
- `/strategy`、`/backtests`
- `/research <prompt>`、`/backtest`、`/backtest latest`

本地模式从 `ToolRegistry`、`AgentRun`、`MemoryService`、`StrategyResearchService` 和 `BacktestService` 读取；远程模式调用对应的 FastAPI 列表接口，并通过 `/api/harness/overview` 汇总状态与模型信息。

工作流快捷命令在本地直接调用 `StrategyResearchService.create()` 与 `BacktestService.run()`，远程则调用 `POST /api/strategy/research` 与 `POST /api/backtests`。

真实 TTY 交互会从 `~/.hypertrade/history` 加载 readline 命令历史。有效 prompt 和斜杠命令会写入历史，因此方向键可以召回上一次请求；非 TTY/脚本运行仍保持普通输入行为，不修改终端历史。

运行流式输出使用一组稳定事件：

- `run_started`
- `tool_started`
- `tool_completed`
- `run_completed`
- `run_failed`
- `final`

CLI 会先把这些事件渲染成进度行，再打印最终落库的 run 报告。这是进度流式，不是模型 token
级流式。
当 stdout 是交互式终端时，CLI 会在等待 planner 或 tool 事件期间显示一个 `Thought` /
`Thinking` 状态块；打印正式状态行和最终报告前会清理该动态块。非 TTY 输出仍保持纯文本，
方便脚本和测试消费。`HYPERTRADE_THINKING_ANIMATION=1` 可用于 smoke 强制打开，`0`
可关闭。

报告渲染优先使用结构化 JSON/trace payload。只有 Markdown 的 run 在 Rich/交互式输出下会
渲染成标题、列表、强调和表格，而不是直接打印 Markdown 源码。`HYPERTRADE_RENDERER=plain`
保留原始 Markdown fallback，供自动化脚本使用。
Rich run 输出默认折叠低信号 trace 行：graph 运行时节点、BitPro capability/health 预检行、
以及嵌套 BitPro 子调用会被汇总，不再作为长表全部打印。业务级工具调用仍会显示，并聚合调用
次数。需要审计或排障时，可设置 `HYPERTRADE_TRACE=full` 打印完整 trace 表。

这样 Provider 配置、Tool Call 策略、RAG、Memory、审批门和 trace 持久化仍保持在同一个运行边界内。终端只是 `/harness` 之外的另一个 Harness 入口。
