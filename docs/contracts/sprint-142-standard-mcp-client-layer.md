# Sprint Contract: Standard MCP Client Layer (P1-5 自主性基建)

## Sprint Name

`standard-mcp-client-layer`

## Goal

把"自造 REST 工具映射 + 单工具真 MCP 通路"升级为**通用标准 MCP 客户端层**：
多 server 注册、`tools/list` 动态发现（带缓存）、`tools/call` 任意调用、
指数退避重试、每 server 熔断器。完成后 HyperTrade 可接入任意标准 MCP server
（filesystem/puppeteer/外部系统），工具面从封闭映射升级为开放协议。
BitPro 既有 REST 映射保持不动（兼容 shim，迁移留后续）。

## In Scope

- 新模块 `connectors/mcp_client.py`：
  - `McpServerConfig` / `McpToolDescriptor` / `McpClientRegistry`。
  - Transport 可注入（生产=官方 SDK Streamable HTTP；测试=fake）。
  - 发现缓存（TTL）+ `force_refresh`；重试只针对传输类错误（工具级 isError
    是结构化失败，不重试）；每 server 连续 N 次失败熔断（open→half-open 探针）。
- Settings：`MCP_SERVERS_JSON`（显式白名单配置，空=禁用）。
- Agent 工具面（registry 单一事实来源）：
  - `mcp.discover`（read）：列出已注册 server 与动态发现的工具（有界）。
  - `mcp.invoke_tool`（research_write + 幂等必填——对外部工具保守归类）。
- kernel executor 分支 + system prompt 路由一句。

## Out of Scope

- BitPro REST shim 迁移到新层。
- 动态发现的工具逐个注册为独立 agent 工具（meta-tool 模式已覆盖）。
- stdio transport / SSE transport（仅 Streamable HTTP）。

## Deliverables

- `connectors/mcp_client.py`、`config.py`、`tools/registry.py`、`agent/kernel.py`。
- `tests/test_mcp_client.py`：发现缓存、传输重试、熔断开/半开、isError 不重试、
  结果归一化、settings 解析、治理策略、kernel 分支。

## Done Means

- 配置了 server 时，agent 可发现并调用其任意工具；未配置时两工具返回结构化
  不可用，行为可预期。
- 熔断打开后调用快速失败，半开探针成功即恢复。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_mcp_client.py tests/test_tool_registry.py tests/test_agent_planner.py
./scripts/check.sh
```

## Risks / Notes

- 外部 MCP 工具被保守归类为 research_write（幂等必填）；真正只读的 server
  会多付一次幂等键成本，属可接受保守性。
- 发现缓存 TTL 内工具清单可能过期；`mcp.discover` 支持 force_refresh。

## Handoff

- Next likely step: P1-6 代码工作区工具面（沙箱暴露为 agent 工具）。
