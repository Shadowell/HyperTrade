# 更新日志

HyperTrade 的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
本项目遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 新增
- 完整的文档系统
  - API 参考（中英文）
  - 用户手册（中英文）
  - 开发者指南（中英文）
  - 文档索引
- 视觉资源
  - 项目 Logo（SVG）
  - 架构流程图
- 专业化的 README 展示

## [0.1.0] - 2026-07-05

### 新增
- **Agent 运行时**
  - LangGraph 风格的 AgentKernel，支持图式执行
  - 提供者路由，支持 DeepSeek、OpenAI、Codex、OpenRouter
  - 工具注册表，带策略强制执行（范围、批准、幂等性）
  - 自然语言交互，自动工具选择

- **市场情报**
  - 实时 OKX SWAP 市场数据摄取
  - 技术指标（SMA、EMA、RSI）
  - 多币种比较和相对强度排名
  - 资金费率和持仓量追踪

- **知识系统**
  - RAG，支持 pgvector 支持的引用搜索
  - 审计的 Memory 系统，带标签、置信度、重要性
  - 知识文档扫描和索引

- **策略开发**
  - 证据驱动的研究工作流
  - Backtrader 集成用于回测
  - 多变体实验（基线、快速、保守）
  - 通过门禁条件自动选择赢家
  - 从 Memory 聚合策略库

- **BitPro 集成**
  - MCP 适配器用于策略生命周期操作
  - 回测诊断和结果检索
  - 模拟盘监控
  - 实盘持仓和表现诊断（只读）

- **交易执行**
  - 模拟盘交易，支持完整生命周期控制
  - 需批准的 Testnet 订单执行
  - 风控治理策略强制执行
  - 幂等写入操作，带审计追踪

- **监控与告警**
  - 模拟盘策略的只读监控
  - 连接器健康检查
  - 策略库新鲜度监控
  - 告警系统，支持严重级别

- **客户端界面**
  - CLI，支持命令历史、颜色和远程模式
  - Web 控制台在 `/harness`，使用 React + Vite
  - REST/SSE API，带 OpenAPI 文档
  - 长时间运行的 Agent 任务的流式支持

- **评估与测试**
  - 确定性评估套件，覆盖工具选择、RAG、Memory、风控
  - 报告质量和路由的回归防护
  - pytest 和前端测试的自动化测试

- **基础设施**
  - Docker Compose 部署
  - GitHub Actions CI/CD 流水线
  - 自托管运行器支持
  - PostgreSQL 带 pgvector 扩展
  - 开发支持 SQLite

- **实验性功能**
  - 世界模型，带投资组合状态追踪
  - 防御性操作引擎，带调度

### 变更
- 无（初始版本）

### 废弃
- 无

### 移除
- 无

### 修复
- 无

### 安全
- 特权操作的基于会话的认证
- HttpOnly、SameSite cookies
- BitPro 边界强制执行（仅 MCP/API 契约）
- 所有工具执行的审计追踪
- V1 阻止主网实盘执行

## [0.0.1] - 2026-06-01

### 新增
- 初始项目设置
- 基础 Agent 骨架
- 市场数据摄取概念验证

---

## 版本说明

### 版本 0.1.0 - 生产就绪的 Agent 运行时

这是 HyperTrade 的第一个生产就绪版本，提供了完整的 Agent 驱动的加密货币交易研究和执行环境。

**亮点**：
- 🤖 智能 Agent，支持自然语言交互
- 📊 来自 OKX 的实时市场情报
- 🧪 证据驱动的策略研究和回测
- 🎮 模拟盘交易，支持需批准的 Testnet 执行
- 🔗 通过 MCP 适配器集成 BitPro
- 💾 RAG 知识检索和审计的 Memory
- 🛡️ 治理层，带风控策略强制执行
- 📱 多界面访问（CLI、Web、API）

**破坏性变更**：无（初始版本）

**迁移指南**：不适用

**已知问题**：
- V1 阻止主网实盘执行
- 大型追踪事件表可能随时间影响性能
- 尚未实现 WebSocket 支持（使用 SSE 进行流式传输）

**升级说明**：不适用（初始版本）

---

## 贡献

有关如何贡献到此更新日志的信息，请参阅 [CONTRIBUTING.md](CONTRIBUTING.zh-CN.md)。

## 链接

- [文档](docs/documentation-index.md)
- [API 参考](docs/api-reference.zh-CN.md)
- [用户手册](docs/user-manual.zh-CN.md)
- [开发者指南](docs/developer-guide.zh-CN.md)
