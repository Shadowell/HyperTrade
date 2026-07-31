# HyperTrade 文档中心

欢迎使用 HyperTrade 文档中心。本页面提供所有文档的快速导航。

## 📚 核心文档

### API 参考
完整的 REST API 文档，包含所有端点、参数和响应格式。

- [API Reference (English)](api-reference.md)
- [API 参考（中文）](api-reference.zh-CN.md)

### 用户手册
面向操作员的完整使用指南，涵盖 CLI、Web 界面和所有核心功能。

- [User Manual (English)](user-manual.md)
- [用户手册（中文）](user-manual.zh-CN.md)

### 开发者指南
面向工程师的开发参考，包含架构、扩展指南和最佳实践。

- [Developer Guide (English)](developer-guide.md)
- [开发者指南（中文）](developer-guide.zh-CN.md)

---

## 📖 其他文档

### 项目文档
- [README](../README.md) - 项目概述和快速开始
- [Product Spec](spec.md) - 产品规格和路线图
- [Progress Log](progress.md) - 开发进度记录
- [Deployment Guide](deployment.md) - 部署指南

### 架构文档
详细的系统架构和设计文档：
- [ARC Autonomous Research Core Architecture](architecture/37-arc-autonomous-research-core-architecture.md) - 通用自主进化控制内核设计：六边形解耦架构、闭环控制器与解耦适配器
- [ARC MCTS & Quality-Diversity Search Design](architecture/38-arc-mcts-and-quality-diversity-search-design.md) - MCTS 蒙特卡洛树搜索 + MAP-Elites 网格搜寻引擎设计
- [ARC Red-Blue Adversarial Game Engine Design](architecture/39-arc-adversarial-red-blue-engine-design.md) - 蓝队策略发明 vs. 红队攻击找茬博弈引擎设计
- [ARC Multi-Regime Causal Attribution & Reflexion Design](architecture/40-arc-reflexion-causal-attribution-design.md) - 多 Regime 定量因果归因与 Reflexion 记忆账本设计
- [ARC Voyager-Style Skill Distillation Design](architecture/41-arc-voyager-skill-distillation-design.md) - Voyager 风格 AST 技能自动提取与基因库设计
- [ARC Dynamic Paper Observation Feedback Architecture](architecture/42-arc-dynamic-paper-observation-feedback.md) - 阶段一：模拟盘实盘数据闭环 & 动态衰退自动重练设计
- [ARC Higher-Order Quant Factor Library Architecture](architecture/43-arc-higher-order-quant-factor-library.md) - 阶段二：高阶量化因子（Orderbook失衡、VWAP、ATR通道）算子库设计
- [ARC Red Team Monte Carlo Overfitting Attack Matrix](architecture/44-arc-red-team-monte-carlo-overfitting-matrix.md) - 阶段三：红队蒙特卡洛参数抖动与黑天鹅防过拟合矩阵设计
- [ARC Parallel MCTS Rollout Engine & Distributed MAP-Elites Architecture](architecture/45-arc-parallel-mcts-rollout-engine-design.md) - 阶段四：多 Agent 并行 MCTS 探索引擎设计
- [ARC Portfolio MCTS Co-Evolution Engine & Low-Correlation Allocator](architecture/46-arc-portfolio-mcts-co-evolution-engine.md) - 阶段五：组合级 MCTS 协同演化引擎与低相关性分配器设计
- [ARC Macro & Unstructured Event Causal Factor Engine](architecture/47-arc-macro-unstructured-event-causal-factor-engine.md) - 阶段六：宏观新闻与非结构化事件因果因子化引擎设计
- [ARC Live Canary Vault & Risk Gate Pipeline Architecture](architecture/48-arc-live-canary-vault-and-risk-gate-pipeline.md) - 阶段七：主网 Live 实盘安全金库与 Canary 动态上线机制设计
- [Agent Harness Industrialization & Self-Healing Scaffolding Architecture](architecture/49-agent-harness-industrialization-design.md) - 工业级 Agent 脚手架强化、工具自愈重试与 Hybrid RAG 检索设计
- [Agent Harness Context Compactor & Parallel Tool Pipeline Architecture](architecture/50-agent-harness-context-compactor-and-parallel-tool-pipeline.md) - SOTA 脚手架补齐：动态 Context 压缩修剪与多工具并发流水线设计
- [ARC-AGI-3 Program Synthesis & Grid DSL Solver Engine Architecture](architecture/51-arc-agi-program-synthesis-solver-engine.md) - ARC-AGI-3 (ARC Prize 2026) 程序合成与 2D Grid DSL 解题引擎设计
- [HyperARC: Standalone Program Synthesis & ARC-AGI-3 Engine Architecture](architecture/52-hyperarc-standalone-program-synthesis-engine-design.md) - HyperARC 独立 AGI 程序合成引擎与比赛解题架构设计
- [Industrial Agent Harness 2.0 Architecture Specification](architecture/53-industrial-agent-harness-v2-architecture.md) - 工业级 Agent Harness 2.0 架构重构（并发工具分发、退避重试、水冷剪裁、幂等锁与微观指标）
- [Advanced Context & Memory Management 2.0 Architecture Specification](architecture/54-advanced-context-and-memory-management-v2-architecture.md) - 深度 Context 与 Memory 2.0 架构重构（动态 Token 护城河、 Schema 剪裁、三层记忆金字塔与艾宾浩斯衰减）
- [Autonomous Memory 3.0 Architecture Specification](architecture/55-autonomous-memory-v3-regime-filter-and-reflexion-flusher.md) - 自主进化 Memory 3.0 架构（自动盘后反思刷盘、Regime 感知隔离与记忆冲突裁决）
- [MCP Circuit Breaker & Tool Risk Governance Architecture Specification](architecture/56-mcp-circuit-breaker-and-tool-governance-v2.md) - MCP 熔断器、Schema 展平翻译与三级风险门禁架构
- [DAG Tool Dispatcher & MCP Batch Pipeline Architecture Specification](architecture/57-dag-tool-dispatcher-and-mcp-batch-pipeline.md) - DAG 依赖图分发与 MCP 同源 JSON-RPC 管道聚合架构
- [Tool Result Cache & Prompt Cache Prefix Aligner Architecture Specification](architecture/58-tool-result-cache-and-prompt-cache-prefix-aligner.md) - 工具结果感知 LRU 缓存与 Prompt Caching KV 前缀对齐架构
- [Agent Flight Recorder & Replay Telemetry Architecture Specification](architecture/59-agent-flight-recorder-and-replay-telemetry.md) - Agent 黑盒飞行记录仪与全轨迹单步重放架构
- [Autonomous Quant Trader North Star](architecture/35-autonomous-quant-trader-north-star.md) - 最终产品目标：持续策略进化、市场状态感知、组合优化与授权内实盘生命周期
- [Goal-Driven Autonomous Research Loop M0](architecture/36-goal-driven-autonomous-research-loop-m0.md) - 自然语言目标、候选生成、真实 BitPro 回测、证据迭代和预授权模拟盘闭环
- [Next-Generation Agent Runtime Audit and Target Design](architecture/34-next-generation-agent-runtime-audit-and-target-design.md) - 真实执行审计、目标协议、完整状态机、Schema、权限、多 Agent、交易安全、评测与切换路线
- [System Architecture](architecture/33-system-architecture.md) - 当前实现快照、Mission Runtime、控制/数据平面、信任边界、安全与部署
- [System Architecture Diagram](architecture/19-hypertrade-architecture-diagram.md)
- [Tool Calling Design](architecture/04-tool-calling.md)
- [Agent Graph Runtime](architecture/12-agent-graph-langgraph-runtime.md)
- [Risk Engine](architecture/14-risk-engine.md)
- [Connector Framework](architecture/20-connector-framework.md)
- [Autonomous Strategy Research Institution](architecture/23-autonomous-strategy-research-institution.md)
- [Agent Research OS Roadmap](architecture/27-agent-research-os-roadmap.md)
- [Agent Research OS Technical Design](architecture/28-agent-research-os-technical-design.md)
- [Research Operations and Shadow Portfolio Roadmap](architecture/29-research-operations-shadow-portfolio-roadmap.md)
- [Professional Agent Runtime V2 Roadmap](architecture/30-professional-agent-runtime-v2-roadmap.md)
- [Professional Agent Runtime V2 Technical Design](architecture/31-professional-agent-runtime-v2-technical-design.md)

### 知识库
操作指南和最佳实践：
- [Knowledge Base](knowledge/) - 知识库目录
- [Tool Usage Guide](knowledge/tool-usage-guide.md)
- [Strategy Research Playbook](knowledge/strategy-research-playbook.md)

### 运行手册
运维程序和故障排除：
- [Runbooks](runbooks/) - 运行手册目录
- [Deployment Smoke Test](runbooks/deployment-smoke.md)
- [Monitoring & Alerts](runbooks/monitoring-alerts.md)
- [Incident Response](runbooks/incident-response.md)

### 合约文档
冲刺合约和功能范围：
- [Contracts](contracts/) - 合约目录
- 各冲刺的详细交付范围和技术规格
- [Sprint 81–84 Research Institution Plan](architecture/23-autonomous-strategy-research-institution.md#分期实施)
- [Sprint 96–105 Agent Research OS Plan](architecture/27-agent-research-os-roadmap.md#6-分期路线)
- [Sprint 106–110 Research Operations Plan](architecture/29-research-operations-shadow-portfolio-roadmap.md#5-分期计划)
- [Sprint 111–116 Professional Agent Runtime V2 Plan](architecture/30-professional-agent-runtime-v2-roadmap.md#7-sprint-路线)
- [Sprint 121 Canonical Thread/Turn Protocol](contracts/sprint-121-canonical-thread-turn-protocol.md) - Remote CLI 首个垂直切换合同（Proposed）
- [Sprint 122–134 Autonomous Quant Trader Delivery Contracts](architecture/35-autonomous-quant-trader-north-star.md#交付合同序列) - 从 Web canonical cutover、Outcome、新旧策略双轨研究到 Live Canary 和有限自主组合 Pilot
- [Active M0 Autonomous Research Contract](contracts/user-directed-autonomous-strategy-research-loop-m0.md) - 当前执行合同；Sprint 132–134 保持未激活

---

## 🚀 快速链接

### 新用户
1. 阅读 [README](../README.md) 了解项目
2. 参考[用户手册](user-manual.zh-CN.md)开始使用
3. 查看 [API 参考](api-reference.zh-CN.md)了解接口

### 开发者
1. 阅读[开发者指南](developer-guide.zh-CN.md)搭建环境
2. 查看[架构文档](architecture/)了解系统设计
3. 参考[合约文档](contracts/)了解功能范围

### 操作员
1. 使用[用户手册](user-manual.zh-CN.md)学习操作
2. 查阅[知识库](knowledge/)了解最佳实践
3. 参考[运行手册](runbooks/)处理运维问题

---

## 📝 文档贡献

文档遵循以下原则：

### 何时创建文档
- 用户明确要求
- 内容具有长期维护价值
- 变更引入新的长期约定
- 文档是任务目标本身

### 何时不创建文档
- 仅为说明本轮改动
- 内容只与当前对话相关
- 代码本身已足够清晰
- 信息已存在于其他文档

详见项目规则：[AGENTS.md](../AGENTS.md)

---

## 🔍 文档搜索

使用 RAG 搜索文档内容：

**CLI**:
```bash
/rag <关键词>
```

**API**:
```bash
curl "http://localhost:3334/api/rag/search?query=<关键词>&limit=5"
```

---

## 📮 反馈与支持

- **问题报告**：通过仓库提交 Issue
- **功能建议**：在 Issue 中标记为 Enhancement
- **文档改进**：提交 Pull Request

---

## 📄 许可证

本项目采用 [MIT License](../LICENSE)。保护密钥、提供者密钥、OKX 凭证、BitPro 令牌、数据库文件和生产 `.env` 文件，不要提交到版本控制。
