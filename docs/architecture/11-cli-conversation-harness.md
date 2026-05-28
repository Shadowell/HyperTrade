# 11 CLI Conversation Harness / CLI 对话 Harness

## English

The CLI is a thin developer harness over the deployed FastAPI API. It does not create a second Agent runtime. `hypertrade ask` and `hypertrade chat` authenticate with `/api/auth/login`, call `/api/agent/runs`, and print the run id, status, tool trace, and Markdown report.

Configuration is environment-based:

- `HYPERTRADE_API_URL` selects the API endpoint.
- `HYPERTRADE_USERNAME` and `HYPERTRADE_PASSWORD` provide admin credentials.
- `HYPERTRADE_TIMEOUT_SECONDS` controls HTTP timeout.

This keeps Provider configuration, Tool Call policy, RAG, Memory, approval gates, and trace persistence on the server. The terminal becomes another harness surface alongside `/harness`.

## 中文

CLI 是部署后 FastAPI API 之上的轻量开发者 Harness，不创建第二套 Agent 运行时。`hypertrade ask` 和 `hypertrade chat` 会先调用 `/api/auth/login` 登录，再调用 `/api/agent/runs`，并输出 run id、状态、工具 trace 和 Markdown 报告。

配置通过环境变量完成：

- `HYPERTRADE_API_URL` 选择 API 地址。
- `HYPERTRADE_USERNAME` 与 `HYPERTRADE_PASSWORD` 提供管理员凭据。
- `HYPERTRADE_TIMEOUT_SECONDS` 控制 HTTP 超时。

这样 Provider 配置、Tool Call 策略、RAG、Memory、审批门和 trace 持久化仍全部留在服务端。终端只是 `/harness` 之外的另一个 Harness 入口。
