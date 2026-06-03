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

DeepSeek, OpenAI, OpenRouter, and Qwen chat use OpenAI-compatible chat completion adapters. Anthropic, Gemini, and Ollama remain extension slots. Runtime selection affects chat/planning only; Qwen embedding remains separate for RAG.

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

DeepSeek、OpenAI、OpenRouter、Qwen chat 使用 OpenAI-compatible adapter。Anthropic、Gemini、Ollama 保留扩展位。Provider 切换只影响 chat/planner，不影响 RAG embedding。
