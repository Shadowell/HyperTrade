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

## 中文

ProviderRuntime 展示模型 Provider 的配置状态，但不返回密钥。DeepSeek 官方 API 是默认聊天模型；Qwen embedding 单独用于 RAG。

Provider 状态包含：

- name 和 display name
- base URL
- model
- enabled/missing 状态
- default 标记

密钥只从环境变量或服务器 `.env` 读取。

