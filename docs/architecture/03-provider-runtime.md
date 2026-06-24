# 03 Provider Runtime / Provider 运行时

## English

ProviderRuntime exposes configured model providers without returning secrets. DeepSeek official API is the default chat provider. Qwen embedding is configured separately for RAG.

Provider records expose:

- name and display name
- base URL
- model
- enabled/missing status
- default flag

Secrets are read only from environment variables or server `.env`.

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

## 中文

ProviderRuntime 展示模型 Provider 的配置状态，但不返回密钥。DeepSeek 官方 API 是默认聊天模型；Qwen embedding 单独用于 RAG。

Provider 状态包含：

- name 和 display name
- base URL
- model
- enabled/missing 状态
- default 标记

密钥只从环境变量或服务器 `.env` 读取。

## Sprint 25 更新

ProviderRuntime 现在不仅展示配置，也负责把 chat/planner 调用路由到 `ChatProvider` 协议。

运行入口：

- API `POST /api/harness/provider-selection`
- CLI `/model` 与 `/model <provider>`
- 前端 `/harness` provider 下拉选择

DeepSeek、OpenAI、OpenRouter、Qwen chat 使用 OpenAI-compatible adapter。Codex 使用指向 Codex backend 的 Responses API 专用 adapter，并接受 `openai-codex` 作为 `codex` 的别名。Anthropic、Gemini、Ollama 保留扩展位。Provider 切换只影响 chat/planner，不影响 RAG embedding。
