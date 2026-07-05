# HyperTrade FAQ (Frequently Asked Questions)

常见问题解答

---

## 📌 通用问题

### Q: HyperTrade 是什么？

**A**: HyperTrade 是一个生产级的 Agent 驱动加密货币交易研究与执行框架。它提供了统一的环境，用于市场研究、策略开发、模拟盘交易和受控的 Testnet 执行。

### Q: HyperTrade 可以用于实盘交易吗？

**A**: V1 版本阻止了主网实盘交易。当前支持：
- ✅ 模拟盘交易（无风险）
- ✅ OKX Testnet 执行（需批准）
- ❌ 主网实盘交易（V1 阻止）

### Q: 这个项目是开源的吗？

**A**: 这是一个私有仓库。请勿未经授权复制、分发或使用。

### Q: 支持哪些交易所？

**A**: 当前版本支持：
- OKX (SWAP 永续合约)
- BitPro（通过 MCP 集成）

未来计划支持 Binance、Bybit 等。

---

## 🚀 安装与配置

### Q: 如何安装 HyperTrade？

**A**: 基本步骤：
```bash
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade
cp .env.example .env
# 编辑 .env 填入 API 密钥
uv sync
npm exec --yes pnpm@10 -- -C frontend install
```

详见[用户手册](user-manual.md#快速开始)。

### Q: 最小配置需要哪些？

**A**: 最小配置：
- Python 3.12+
- `uv` 包管理器
- `DEEPSEEK_API_KEY`（或其他聊天提供者）
- SQLite（无需 PostgreSQL）

### Q: 支持哪些聊天提供者？

**A**: 支持的提供者：
- DeepSeek（默认）
- OpenAI
- Codex
- OpenRouter
- Qwen（可扩展）

在 `.env` 中配置相应的 API 密钥。

### Q: 必须使用 PostgreSQL 吗？

**A**: 
- **开发**: 可以使用 SQLite，快速启动
- **生产**: 推荐使用 PostgreSQL + pgvector
  - 更好的并发性能
  - 支持 RAG 向量搜索

---

## 💻 使用问题

### Q: 如何使用 CLI？

**A**: 
```bash
# 本地模式
uv run ht --local

# 远程模式（首次需要登录）
uv run ht /login
uv run ht
```

常用命令：`/help`, `/price ETH`, `/paper`, `/research`

### Q: Web 界面在哪里访问？

**A**: 
- 本地开发：http://localhost:3333/harness
- 生产环境：http://your-server:3333/harness

### Q: 如何切换聊天提供者？

**A**: 
```bash
# CLI
/model

# API
POST /api/harness/provider-selection
```

### Q: 自然语言提示不工作？

**A**: 检查：
1. 是否配置了聊天提供者 API 密钥
2. 运行 `/model` 查看提供者状态
3. 使用确定性命令（如 `/price`）不需要提供者

---

## 📊 市场数据

### Q: 市场数据从哪里来？

**A**: 
- OKX REST API：历史数据、K线
- OKX WebSocket：实时行情推送
- BitPro：通过 MCP 适配器访问

### Q: 市场数据为空怎么办？

**A**: 检查：
1. Worker 是否运行：`docker compose ps`
2. OKX 配置：`OKX_REST_URL`, `OKX_PUBLIC_WS_URL`
3. 网络连接是否正常
4. 查看 worker 日志：`docker compose logs worker`

### Q: 支持哪些时间级别的 K线？

**A**: 支持的时间级别：
- 分钟：`1m`, `5m`, `15m`, `30m`
- 小时：`1H`, `4H`
- 天：`1D`

---

## 🧪 策略研究

### Q: 如何开始策略研究？

**A**: 
```bash
# 1. 创建研究记录
/research 研究ETH趋势突破策略

# 2. 运行回测
/backtest

# 3. 多变体实验
/experiment 实验不同参数

# 4. 查看策略库
/strategy library <name>
```

### Q: 回测使用什么引擎？

**A**: 使用 Backtrader 回测引擎。支持：
- 自定义策略逻辑
- 多种数据源（OKX、BitPro、样本数据）
- 完整的交易成本模拟
- 详细的权益曲线和交易记录

### Q: 策略实验的三个变体是什么？

**A**: 
- **baseline**: 标准参数
- **fast**: 更激进的参数（更快响应）
- **conservative**: 更保守的参数（更低风险）

系统自动选择表现最好的变体。

### Q: 如何查看历史策略证据？

**A**: 
```bash
/strategy library <strategy_name>
```

返回：
- 所有证据记录
- 平均置信度
- 最新实验结果
- 改进建议

---

## 🎮 模拟盘与实盘

### Q: 模拟盘如何工作？

**A**: 模拟盘是完全独立的虚拟交易环境：
- 无真实资金风险
- 使用真实市场数据
- 支持暂停/恢复/重置
- 完整的持仓和 PnL 跟踪

### Q: 如何创建 Testnet 订单？

**A**: 
```bash
# 1. 创建订单意图
/live intent ETH buy 0.01 reason="测试"

# 2. 批准订单
/live approve loi_abc123

# 3. 执行订单
/live execute loi_abc123
```

需要配置 OKX Testnet 凭证。

### Q: 为什么订单需要批准？

**A**: 安全原因：
- 人工审核避免错误订单
- 风控检查（名义价值、开仓数量）
- 审计追踪
- 幂等性验证

### Q: 可以在主网上交易吗？

**A**: V1 版本不支持主网交易。这是有意设计的安全限制。

---

## 🔗 BitPro 集成

### Q: 什么是 BitPro？

**A**: BitPro 是基础交易系统平台，负责：
- 策略存储和执行
- 回测引擎
- 模拟盘运行时
- 实盘订单管理

HyperTrade 通过 MCP 适配器访问 BitPro。

### Q: BitPro 工具返回 502 错误？

**A**: 检查：
1. `BITPRO_MCP_API_BASE` 是否正确
2. `BITPRO_MCP_API_TOKEN` 是否有效
3. BitPro 服务是否运行
4. 访问 `/api/bitpro/health` 检查连接

### Q: HyperTrade 会直接访问 BitPro 数据库吗？

**A**: **不会**。HyperTrade 只通过 MCP/API 契约访问 BitPro，永远不会：
- 直接读取 BitPro 数据库
- 复制 BitPro 业务逻辑
- 绕过 BitPro 风险边界

---

## 📚 RAG 与 Memory

### Q: RAG 和 Memory 有什么区别？

**A**: 
- **RAG**: 从文档中检索知识（`docs/knowledge`）
  - 静态文档内容
  - 源引用和引证
  
- **Memory**: 存储运行时观察和策略证据
  - 动态生成的知识
  - 标签、置信度、重要性

### Q: RAG 搜索无结果？

**A**: 检查：
1. `KNOWLEDGE_DIR` 配置是否正确
2. `docs/knowledge/` 目录是否有文档
3. RAG 扫描是否完成（查看日志）
4. 尝试更广泛的查询词

### Q: 如何添加自定义知识文档？

**A**: 
1. 在 `docs/knowledge/` 中添加 Markdown 文件
2. 重启服务或等待自动扫描
3. 使用 `/rag <query>` 搜索

---

## 🔧 故障排除

### Q: 提示返回 `provider_unavailable`？

**A**: 
1. 检查聊天提供者 API 密钥
2. 运行 `/model` 查看配置
3. 使用确定性命令（如 `/price`）不需要提供者

### Q: Web 界面加载很慢？

**A**: 可能原因：
1. 使用 SQLite（推荐 PostgreSQL）
2. 数据量过大（清理旧运行记录）
3. 首次加载需要时间

优化：
```bash
# 使用 PostgreSQL
docker compose up -d postgres
export DATABASE_URL="postgresql://..."
```

### Q: CLI 命令历史不工作？

**A**: 确保：
1. 在真实终端中运行（不是管道或脚本）
2. 使用最新版本
3. readline 库已安装

### Q: Docker 容器无法启动？

**A**: 检查：
1. Docker 和 Docker Compose 已安装
2. 端口 3333、3334、5432 未被占用
3. `.env` 文件配置正确
4. 查看容器日志：`docker compose logs`

---

## 🔒 安全问题

### Q: 如何保护 API 密钥？

**A**: 
- 使用 `.env` 文件存储密钥
- 永远不要提交 `.env` 到版本控制
- 生产环境使用环境变量或密钥管理器
- 定期轮换密钥

### Q: 谁可以访问 Web 界面？

**A**: 
- 读取端点：公开访问
- 写入操作：需要管理员认证
- 生产环境：使用 Nginx + TLS

### Q: 如何报告安全漏洞？

**A**: 请勿通过公开 Issue 报告。直接联系仓库所有者。详见 [SECURITY.md](../SECURITY.md)。

---

## 📈 性能问题

### Q: 能支持多少并发运行？

**A**: 
- Agent 运行：~5-10 并发（受提供者速率限制）
- API 请求：无硬限制（计划添加速率限制）
- WebSocket：尚未实现（使用 SSE）

### Q: 数据库会变得很大吗？

**A**: 是的，追踪事件会随时间积累。建议：
- 定期清理旧运行记录
- 实施保留策略
- 使用 PostgreSQL（比 SQLite 更好的性能）

---

## 🚀 部署问题

### Q: 如何部署到生产环境？

**A**: 
```bash
# 自动部署（推荐）
git push origin main
# GitHub Actions 自动部署

# 手动部署
ssh your-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

详见[部署指南](deployment.md)。

### Q: 需要什么样的服务器？

**A**: 最小要求：
- 2 CPU 核心
- 4GB RAM
- 20GB 存储
- Ubuntu 20.04+ 或类似 Linux 发行版

推荐：
- 4 CPU 核心
- 8GB RAM
- 50GB SSD

### Q: 如何备份数据？

**A**: 
```bash
# PostgreSQL 备份
pg_dump hypertrade > backup.sql

# SQLite 备份
cp hypertrade.db backup.db
```

详见[备份运行手册](runbooks/backup-restore.md)。

---

## 🤝 贡献问题

### Q: 如何贡献代码？

**A**: 
1. 阅读 [CONTRIBUTING.md](../CONTRIBUTING.md)
2. 检查活动的 Sprint 合约
3. 遵循代码规范
4. 运行 `./scripts/check.sh` 测试
5. 提交 Pull Request（未来）

### Q: 发现 Bug 怎么办？

**A**: 
1. 检查是否已有相关 Issue
2. 提供详细的复现步骤
3. 包含日志和错误信息
4. 说明环境（OS、Python 版本等）

---

## 📚 更多帮助

### Q: 文档在哪里？

**A**: 
- **文档中心**: [docs/documentation-index.md](documentation-index.md)
- **API 参考**: [docs/api-reference.md](api-reference.md)
- **用户手册**: [docs/user-manual.md](user-manual.md)
- **开发者指南**: [docs/developer-guide.md](developer-guide.md)
- **快速参考**: [docs/QUICK_REFERENCE.md](QUICK_REFERENCE.md)

### Q: 如何获取支持？

**A**: 
1. 查看文档和 FAQ
2. 搜索已有 Issue
3. 提交新 Issue（包含详细信息）
4. 联系仓库所有者

### Q: 有中文文档吗？

**A**: 是的！所有核心文档都提供中英文版本：
- [API 参考（中文）](api-reference.zh-CN.md)
- [用户手册（中文）](user-manual.zh-CN.md)
- [开发者指南（中文）](developer-guide.zh-CN.md)

---

**还有问题？** 查看[完整文档](documentation-index.md)或提交 Issue。
