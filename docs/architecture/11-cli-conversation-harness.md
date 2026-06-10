# 11 CLI Conversation Harness / CLI 对话 Harness

## English

The CLI is a developer harness with two runtime modes:

- Local standalone mode: `hypertrade`, `hypertrade chat`, or `hypertrade ask <prompt>` load `Settings`, connect to the configured database, create an `AgentKernel`, and persist runs/traces through the same backend services.
- Remote API mode: `hypertrade --remote <url>` authenticates with `/api/auth/login`, prefers `POST /api/agent/runs/stream` for Server-Sent Events, and falls back to `/api/agent/runs` style full-run rendering when streaming is unavailable.

Configuration is environment-based:

- `HYPERTRADE_API_URL` selects the API endpoint and makes remote mode the default unless `--local` is passed.
- `HYPERTRADE_USERNAME` and `HYPERTRADE_PASSWORD` provide admin credentials.
- `HYPERTRADE_TIMEOUT_SECONDS` controls HTTP timeout.

Interactive chat also supports slash commands for harness inspection without starting a new Agent run.
`/help` renders every command with a short purpose statement, and `/tools` renders each
registered Agent tool with category, approval marker, and registry description:

- `/help`, `/status`, `/model`, `/providers`
- `/tools`, `/runs`, `/memory`
- `/strategy`, `/backtests`
- `/research <prompt>`, `/backtest`, `/backtest latest`

Local mode reads these from `ToolRegistry`, `AgentRun`, `MemoryService`, `StrategyResearchService`, and `BacktestService`. Remote mode calls the matching FastAPI list endpoints and `/api/harness/overview` for status/model summaries.

Workflow shortcuts call `StrategyResearchService.create()` and `BacktestService.run()` locally, or `POST /api/strategy/research` and `POST /api/backtests` remotely.

Run streaming uses a small stable event shape:

- `run_started`
- `tool_started`
- `tool_completed`
- `run_completed`
- `run_failed`
- `final`

The CLI renders these as progress lines before printing the final stored run report. This is
progress streaming, not token-by-token model streaming.

This keeps Provider configuration, Tool Call policy, RAG, Memory, approval gates, and trace persistence in one runtime boundary. The terminal becomes another harness surface alongside `/harness`.

## 中文

CLI 是开发者 Harness，支持两种运行模式：

- 本地 standalone 模式：`hypertrade`、`hypertrade chat` 或 `hypertrade ask <prompt>` 会加载 `Settings`，连接配置的数据库，创建 `AgentKernel`，并通过同一套后端服务持久化 run/trace。
- 远程 API 模式：`hypertrade --remote <url>` 会调用 `/api/auth/login` 登录，优先通过
  `POST /api/agent/runs/stream` 消费 Server-Sent Events；如果流式不可用，再回退到完整 run
  输出。

配置通过环境变量完成：

- `HYPERTRADE_API_URL` 选择 API 地址，并让远程模式成为默认；传 `--local` 可以强制本地模式。
- `HYPERTRADE_USERNAME` 与 `HYPERTRADE_PASSWORD` 提供管理员凭据。
- `HYPERTRADE_TIMEOUT_SECONDS` 控制 HTTP 超时。

交互式 chat 还支持斜杠命令，用于查看 Harness 状态而无需发起新的 Agent run。`/help`
会为每条命令显示用途说明，`/tools` 会为每个 Agent 工具显示 category、approval 标记和
registry 描述：

- `/help`、`/status`、`/model`、`/providers`
- `/tools`、`/runs`、`/memory`
- `/strategy`、`/backtests`
- `/research <prompt>`、`/backtest`、`/backtest latest`

本地模式从 `ToolRegistry`、`AgentRun`、`MemoryService`、`StrategyResearchService` 和 `BacktestService` 读取；远程模式调用对应的 FastAPI 列表接口，并通过 `/api/harness/overview` 汇总状态与模型信息。

工作流快捷命令在本地直接调用 `StrategyResearchService.create()` 与 `BacktestService.run()`，远程则调用 `POST /api/strategy/research` 与 `POST /api/backtests`。

运行流式输出使用一组稳定事件：

- `run_started`
- `tool_started`
- `tool_completed`
- `run_completed`
- `run_failed`
- `final`

CLI 会先把这些事件渲染成进度行，再打印最终落库的 run 报告。这是进度流式，不是模型 token
级流式。

这样 Provider 配置、Tool Call 策略、RAG、Memory、审批门和 trace 持久化仍保持在同一个运行边界内。终端只是 `/harness` 之外的另一个 Harness 入口。
