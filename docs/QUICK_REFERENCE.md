# HyperTrade Quick Reference

快速参考指南，涵盖最常用的命令、API 端点和配置参数。

---

## 📋 CLI 命令速查表

### 系统信息

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/status` | 系统状态概览 |
| `/model` | 查看/切换聊天提供者和模型 |
| `/tools` | 列出所有可用工具 |
| `/evals` | 查看评估套件状态 |
| `/connectors` | 查看连接器状态 |

### 市场数据

| 命令 | 说明 | 示例 |
|------|------|------|
| `/price <symbol>` | 查看币种价格 | `/price ETH` |
| `/candles <symbol> <bar> <limit>` | 获取K线数据 | `/candles BTC 1H 120` |
| `/compare <symbols...>` | 比较多个币种 | `/compare BTC ETH SOL` |

### 策略研究

| 命令 | 说明 | 示例 |
|------|------|------|
| `/research <prompt>` | 创建研究记录 | `/research 研究ETH趋势策略` |
| `/backtest` | 运行回测 | `/backtest` |
| `/experiment <prompt>` | 策略实验 | `/experiment 测试动量策略` |
| `/strategy library <name>` | 查询策略库 | `/strategy library momentum_v1` |

### 模拟盘

| 命令 | 说明 |
|------|------|
| `/paper` | 查看模拟盘状态 |
| `/paper pause [symbol]` | 暂停交易 |
| `/paper resume` | 恢复交易 |
| `/paper close` | 平掉所有仓位 |
| `/paper reset` | 重置模拟盘 |

### 实盘订单（Testnet）

| 命令 | 说明 | 示例 |
|------|------|------|
| `/live intent <symbol> <side> <size> reason="..."` | 创建订单意图 | `/live intent ETH buy 0.01 reason="测试"` |
| `/live intents` | 列出订单意图 | `/live intents` |
| `/live approve <intent_id>` | 批准订单 | `/live approve loi_abc123` |
| `/live reject <intent_id>` | 拒绝订单 | `/live reject loi_abc123` |
| `/live execute <intent_id>` | 执行订单 | `/live execute loi_abc123` |

### 知识检索

| 命令 | 说明 | 示例 |
|------|------|------|
| `/rag <query>` | 搜索知识库 | `/rag 风控` |
| `/memory search <query>` | 搜索 Memory | `/memory search tag:strategy` |

### 监控

| 命令 | 说明 |
|------|------|
| `/monitors` | 列出所有监控器 |
| `/monitor run <monitor_id>` | 运行监控 |
| `/alerts` | 查看告警 |

### 运行历史

| 命令 | 说明 |
|------|------|
| `/runs` | 查看最近的运行 |
| `/run <run_id>` | 查看运行详情 |

---

## 🔌 API 端点速查表

### 基础

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/harness/overview` | 系统概览 |
| `GET` | `/api/harness/tools` | 工具列表 |
| `GET` | `/api/harness/providers` | 提供者列表 |

### 认证

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/auth/login` | 登录 |
| `POST` | `/api/auth/logout` | 登出 |
| `GET` | `/api/auth/me` | 当前用户 |

### Agent 运行

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/agent/runs` | 创建运行 |
| `POST` | `/api/agent/runs/stream` | 流式运行 (SSE) |
| `GET` | `/api/agent/runs` | 列出运行 |
| `GET` | `/api/agent/runs/{run_id}` | 运行详情 |
| `POST` | `/api/agent/runs/{run_id}/cancel` | 取消运行 |

### 市场数据

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/market/tickers/latest` | 所有行情 |
| `GET` | `/api/market/ticker/{symbol}` | 单个行情 |
| `GET` | `/api/market/candles/{symbol}` | K线数据 |
| `POST` | `/api/market/compare` | 比较币种 |

### RAG & Memory

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/rag/search?query=<q>` | RAG 搜索 |
| `GET` | `/api/memory?query=<q>` | Memory 搜索 |
| `DELETE` | `/api/memory/{memory_id}` | 删除 Memory |

### 策略与回测

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/strategy/research` | 创建研究 |
| `GET` | `/api/strategy/research` | 研究列表 |
| `POST` | `/api/strategy/experiments` | 创建实验 |
| `GET` | `/api/strategy/library` | 策略库 |
| `POST` | `/api/backtests` | 创建回测 |
| `GET` | `/api/backtests` | 回测列表 |

### 模拟盘

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/paper/status` | 模拟盘状态 |
| `POST` | `/api/paper/control` | 控制操作 |

### 实盘订单

| 方法 | 端点 | 说明 |
|------|------|------|
| `POST` | `/api/live/order-intents` | 创建订单意图 |
| `GET` | `/api/live/order-intents` | 订单意图列表 |
| `POST` | `/api/live/order-intents/{id}/approve` | 批准订单 |
| `POST` | `/api/live/order-intents/{id}/reject` | 拒绝订单 |
| `POST` | `/api/live/order-intents/{id}/execute` | 执行订单 |

### BitPro 集成

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/bitpro/health` | BitPro 健康检查 |
| `GET` | `/api/bitpro/market/klines/{symbol}` | BitPro K线 |
| `GET` | `/api/bitpro/paper/dashboard` | 模拟盘仪表板 |
| `GET` | `/api/bitpro/live/positions` | 实盘持仓 |

### 监控与告警

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/monitors` | 监控器列表 |
| `POST` | `/api/monitors/{id}/run` | 运行监控 |
| `GET` | `/api/alerts` | 告警列表 |

### 评估

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/evals/status` | 评估状态 |

---

## ⚙️ 配置参数速查表

### 核心配置

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | 数据库连接字符串 | `sqlite:///./hypertrade.db` |
| `APP_ENV` | 应用环境 | `development`, `production` |
| `API_HOST` | API 主机 | `0.0.0.0` |
| `API_PORT` | API 端口 | `3334` |

### 认证与安全

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SESSION_SECRET` | 会话密钥 | - |
| `ADMIN_USERNAME` | 管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 管理员密码 | - |
| `COOKIE_SECURE` | 启用安全 Cookie | `false` |

### 聊天提供者

| 变量 | 说明 |
|------|------|
| `ACTIVE_CHAT_PROVIDER` | 活动提供者 (`deepseek`, `openai`, `codex`) |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `CODEX_API_KEY` | Codex API 密钥 |
| `CODEX_AUTH_JSON` | Codex 认证 JSON |
| `CODEX_MODEL` | Codex 模型名称 |

### 嵌入与 RAG

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QWEN_API_KEY` | Qwen API 密钥 | - |
| `QWEN_EMBEDDING_MODEL` | 嵌入模型 | `text-embedding-v3` |
| `KNOWLEDGE_DIR` | 知识库目录 | `docs/knowledge` |
| `RAG_SCAN_INTERVAL_SECONDS` | RAG 扫描间隔 | `300` |

### OKX

| 变量 | 说明 |
|------|------|
| `OKX_API_KEY` | OKX API 密钥 |
| `OKX_API_SECRET` | OKX API 密钥 |
| `OKX_PASSPHRASE` | OKX 口令 |
| `OKX_TESTNET` | 启用 Testnet | `true`/`false` |
| `OKX_REST_URL` | REST API URL |
| `OKX_PUBLIC_WS_URL` | WebSocket URL |

### 模拟盘与风控

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PAPER_ENABLED` | 启用模拟盘 | `true` |
| `PAPER_STARTING_EQUITY_USDT` | 初始资金 | `100000` |
| `RISK_MAX_ORDER_NOTIONAL_USDT` | 最大订单名义价值 | `10000` |
| `RISK_MAX_OPEN_INTENTS` | 最大待处理订单数 | `5` |

### BitPro

| 变量 | 说明 |
|------|------|
| `BITPRO_MCP_API_BASE` | BitPro MCP 基础 URL |
| `BITPRO_MCP_API_TOKEN` | BitPro MCP 令牌 |
| `BITPRO_MCP_AUTH_HEADER` | 认证头名称 |
| `BITPRO_MCP_TIMEOUT_SECONDS` | 超时时间 |

### 监控

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MONITOR_SCHEDULER_ENABLED` | 启用自动监控 | `false` |
| `MONITOR_LOOP_INTERVAL_SECONDS` | 监控循环间隔 | `300` |

---

## 🚀 常用工作流

### 市场研究

```bash
# 1. 查看市场概况
uv run hypertrade --local ask "看下目前市场的热度怎么样"

# 2. 查看特定币种
/price ETH

# 3. 技术分析
/candles BTC 1H 120

# 4. 比较币种
/compare ETH SOL BTC
```

### 策略开发

```bash
# 1. 创建研究记录
/research 研究ETH趋势突破策略

# 2. 运行回测
/backtest

# 3. 多变体实验
/experiment 实验ETH动量策略的不同参数

# 4. 查看策略库
/strategy library momentum_breakout_v1
```

### 模拟盘操作

```bash
# 1. 检查状态
/paper

# 2. 暂停交易
/paper pause BTC

# 3. 恢复交易
/paper resume

# 4. 平仓重置
/paper close
/paper reset
```

### Testnet 订单

```bash
# 1. 创建订单意图
/live intent ETH buy 0.01 reason="API 测试"

# 2. 查看待处理订单
/live intents

# 3. 批准订单
/live approve loi_abc123

# 4. 执行订单
/live execute loi_abc123
```

---

## 🔧 快速故障排除

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 提示返回 `provider_unavailable` | 未配置提供者密钥 | 检查 `DEEPSEEK_API_KEY`，运行 `/model` |
| BitPro 工具返回 502 | BitPro MCP 连接问题 | 检查 `BITPRO_MCP_API_BASE` 和令牌 |
| 市场数据为空 | Worker 未运行 | 检查 worker 日志和 OKX 配置 |
| RAG 搜索无结果 | 知识库未扫描 | 检查 `KNOWLEDGE_DIR` 配置 |
| Testnet 订单失败 | 缺少凭证或风控拒绝 | 检查 OKX Testnet 凭证和风控设置 |

---

## 📚 更多资源

- **完整文档**: [docs/documentation-index.md](../documentation-index.md)
- **API 参考**: [docs/api-reference.md](../api-reference.md)
- **用户手册**: [docs/user-manual.md](../user-manual.md)
- **开发者指南**: [docs/developer-guide.md](../developer-guide.md)

---

**提示**: 使用 `/help` 命令查看完整的命令列表和说明。
