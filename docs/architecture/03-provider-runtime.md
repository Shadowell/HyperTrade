# 03 Provider Runtime / Provider 运行时

## English

ProviderRuntime exposes configured model providers without returning secrets. DeepSeek official API is the default chat provider. Qwen embedding is configured separately for RAG.

Provider records expose:

- name and display name
- base URL
- model
- model options where the provider supports session-level model selection
- enabled/missing status
- default flag

Secrets are read only from environment variables or server `.env`.

## Production Codex Activation

The project-level default remains DeepSeek so a new local deployment does not
depend on a ChatGPT OAuth session. A production operator may instead set
`ACTIVE_CHAT_PROVIDER=codex` and `CODEX_MODEL=gpt-5.4` in the server-only
`/opt/hypertrade/.env`. Docker Compose reads the server-local
`CODEX_AUTH_SOURCE_PATH` and mounts it into only the API and worker as the
read-only `hypertrade_codex_auth` secret. The container receives only
`CODEX_AUTH_JSON=/run/secrets/hypertrade_codex_auth`; neither the OAuth content
nor a token is copied into Git, CI, or the environment file. If no source path
is configured, Compose mounts an empty fallback and Codex remains unavailable.

## Sprint 25 Update

ProviderRuntime now routes actual chat/planner calls through a `ChatProvider` protocol.

Runtime surfaces:

- API `POST /api/harness/provider-selection`
- CLI `/model` and `/model <provider>`
- frontend `/harness` provider selector

DeepSeek, OpenAI, OpenRouter, and Qwen chat use OpenAI-compatible chat completion adapters. Codex uses a dedicated Responses API adapter pointed at the Codex backend, with `openai-codex` accepted as an alias for `codex`. Anthropic, Gemini, and Ollama remain extension slots. Runtime selection affects chat/planning only; Qwen embedding remains separate for RAG.

## Sprint 58 Codex Update

Codex is available as a chat/planner provider when either `CODEX_API_KEY` is
set to a bearer token or `CODEX_AUTH_JSON` points to a Codex/Hermes auth file
that contains an `access_token`. The default auth path is `~/.codex/auth.json`,
which matches the local Codex CLI convention; operators may point
`CODEX_AUTH_JSON` at `~/.hermes/auth.json` if they want to reuse Hermes-managed
`openai-codex` tokens.

The Codex adapter converts HyperTrade's existing chat-completions style tool
schemas to Responses API `function` tools, parses Codex `function_call` output
items back into `ToolCallRequest`, and sends trusted HyperTrade tool results
back as `function_call_output` input items. Codex never executes HyperTrade
tools, shell commands, patches, approvals, BitPro actions, or exchange actions
directly.

The ChatGPT Codex backend requires `stream=true` even for HyperTrade's
synchronous planner contract. The adapter keeps the request boundary explicit:
it moves trusted system guidance to the Responses `instructions` field, buffers
the server-sent event stream, and reconstructs `response.output_item.done`
items before applying normal function-call parsing. The model still returns
intent only; HyperTrade's policy and tool executor remain the sole execution
boundary.

## Sprint 61 Codex Model Picker Update

`CODEX_MODEL` remains the default Codex model. `CODEX_MODEL_OPTIONS` is a
comma-separated allowlist used by the API and CLI to present safe selectable
Codex models. API `POST /api/harness/provider-selection` accepts an optional
`model` field, validates it against the provider's `model_options`, and stores
the choice only as session/process state. Interactive CLI `/model` renders a
numbered provider list and, when Codex is selected, a numbered Codex model list;
the selected model is passed into `AgentKernel` for chat/planner calls.

## 中文

ProviderRuntime 展示模型 Provider 的配置状态，但不返回密钥。DeepSeek 官方 API 是默认聊天模型；Qwen embedding 单独用于 RAG。

Provider 状态包含：

- name 和 display name
- base URL
- model
- 支持会话级模型选择时的 model options
- enabled/missing 状态
- default 标记

## 生产 Codex 启用

项目级默认值仍是 DeepSeek，因此新的本地部署不依赖 ChatGPT OAuth 会话。生产
操作员可以只在服务器的 `/opt/hypertrade/.env` 设置
`ACTIVE_CHAT_PROVIDER=codex` 和 `CODEX_MODEL=gpt-5.4`。Docker Compose 从服务器
本地的 `CODEX_AUTH_SOURCE_PATH` 读取认证文件，并且只以只读
`hypertrade_codex_auth` secret 挂载给 API 和 worker。容器只接收
`CODEX_AUTH_JSON=/run/secrets/hypertrade_codex_auth`；OAuth 内容和 token 都不会
复制到 Git、CI 或环境文件。未配置 source path 时，Compose 只挂载空 fallback，
Codex 保持不可用。

密钥只从环境变量或服务器 `.env` 读取。

## Sprint 25 更新

ProviderRuntime 现在不仅展示配置，也负责把 chat/planner 调用路由到 `ChatProvider` 协议。

运行入口：

- API `POST /api/harness/provider-selection`
- CLI `/model` 与 `/model <provider>`
- 前端 `/harness` provider 下拉选择

DeepSeek、OpenAI、OpenRouter、Qwen chat 使用 OpenAI-compatible adapter。Codex 使用指向 Codex backend 的 Responses API 专用 adapter，并接受 `openai-codex` 作为 `codex` 的别名。Anthropic、Gemini、Ollama 保留扩展位。Provider 切换只影响 chat/planner，不影响 RAG embedding。

## Sprint 61 Codex 模型选择更新

`CODEX_MODEL` 仍是 Codex 默认模型。`CODEX_MODEL_OPTIONS` 是逗号分隔的
模型白名单，API 与 CLI 只从这份列表提供可选模型。`POST
/api/harness/provider-selection` 支持可选 `model` 字段，并按
`model_options` 校验后只保存为会话/进程状态。交互式 CLI `/model` 先展示
provider 编号列表；选中 Codex 后再展示 Codex 模型编号列表，最终把选中的模型传给
`AgentKernel` 的 chat/planner 调用。
