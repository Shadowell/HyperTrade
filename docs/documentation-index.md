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
- [Architecture Overview](architecture/) - 架构概览目录
- [Autonomous Quant Trader North Star](architecture/35-autonomous-quant-trader-north-star.md) - 最终产品目标：持续策略进化、市场状态感知、组合优化与授权内实盘生命周期
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
