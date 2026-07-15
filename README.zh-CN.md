# HyperTrade

**Agent 驱动的加密货币交易研究与执行框架**

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://reactjs.org/)

[📖 完整文档](README.md) | [English](README.en.md) | [文档中心](docs/documentation-index.md)

---

## HyperTrade 是什么？

HyperTrade 是一个自托管、受治理的加密市场研究 Agent Runtime。它把开放式目标转化为可恢复的
Mission：版本化计划、有界步骤、证据、预算、操作员控制与可审计交付，并为市场研究、策略开发、
模拟盘观察和受控的 Testnet 意图检查提供统一环境。

模型可以提出工作，但不能自行增加权限、伪造证据或授权交易。HyperTrade 是受控的研究闭环，不是
无人值守的交易机器人；它不承诺盈利，也不构成投资建议。

![HyperTrade 架构](docs/assets/hypertrade-architecture.svg)

**核心能力**：
- 🤖 自然语言交互，自动工具选择
- 📊 实时 OKX 市场数据和技术分析
- 🧪 证据驱动的策略回测和实验
- 🎮 模拟盘交易，支持完整生命周期控制
- ⚡ 需批准的 Testnet 执行（V1 阻止主网）
- 🔗 通过 MCP 适配器集成 BitPro
- 💾 RAG 知识检索和审计的 Memory 系统

> 📖 从[系统架构](docs/architecture/33-system-architecture.md)开始，了解当前 Mission Runtime、
> 数据边界、安全模型和部署拓扑；[可视化架构图](docs/architecture/19-hypertrade-architecture-diagram.md)
> 适合快速讨论系统分层。

---

## 快速开始

### 安装

```bash
git clone git@github.com:Shadowell/HyperTrade.git
cd HyperTrade
cp .env.example .env
# 编辑 .env 文件，填入你的 API 密钥

export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
export DEEPSEEK_API_KEY="your-key"
```

### 运行

**后端**：
```bash
uv run uvicorn hypertrade.main:app --app-dir backend/src --port 3334
```

**前端**：
```bash
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
```

**命令行**：
```bash
uv run ht --local
```

**访问**：
- Web 控制台：http://localhost:3333/harness
- API 文档：http://localhost:3334/docs

---

## 使用示例

### 市场研究
```bash
# 自然语言
uv run hypertrade --local ask "看下目前市场的热度怎么样"

# 确定性命令
/price ETH
/candles BTC 1H 120
/compare ETH SOL BTC
```

### 策略研究
```bash
/research 研究ETH趋势突破策略
/backtest
/experiment 实验ETH动量突破策略的不同参数
/strategy library momentum_breakout_v1
```

### 模拟盘交易
```bash
/paper              # 查看状态
/paper pause BTC    # 暂停 BTC 交易
/paper close        # 平掉所有仓位
```

### 实盘订单（Testnet）
```bash
/live intent ETH buy 0.01 reason="测试"
/live approve loi_abc123
/live execute loi_abc123
```

---

## 架构

```
客户端层 (CLI, Web, API)
    ↓
Agent 运行时 (Kernel, Planner, Tool Executor)
    ↓
治理层 (ToolRegistry, Risk Policy, Trace)
    ↓
服务层 (Market, RAG, Memory, Strategy, Backtest)
    ↓
数据层 (PostgreSQL/SQLite, OKX, BitPro)
```

**技术栈**：
- 后端：Python 3.12+, FastAPI, SQLAlchemy, Backtrader
- 前端：React 18, TypeScript, Vite, TailwindCSS
- 数据库：PostgreSQL 14+ with pgvector（或 SQLite）
- 基础设施：Docker Compose, Nginx, GitHub Actions

当前工作流以 PostgreSQL 中的服务端 Mission 账本为准。Web、CLI、TUI 和桌面伴侣只投影 REST/SSE
状态；经过审核的 Capability Catalog 与风险策略仍是唯一的工具调用授权边界。详见
[完整系统架构](docs/architecture/33-system-architecture.md)。

---

## 文档

| 文档 | 链接 |
|------|------|
| **完整 README** | [README.md](README.md) |
| **系统架构** | [docs/architecture/33-system-architecture.md](docs/architecture/33-system-architecture.md) |
| **API 参考** | [docs/api-reference.zh-CN.md](docs/api-reference.zh-CN.md) |
| **用户手册** | [docs/user-manual.zh-CN.md](docs/user-manual.zh-CN.md) |
| **开发者指南** | [docs/developer-guide.zh-CN.md](docs/developer-guide.zh-CN.md) |
| **文档中心** | [docs/documentation-index.md](docs/documentation-index.md) |
| **架构文档** | [docs/architecture/](docs/architecture/) |
| **产品规格** | [docs/spec.md](docs/spec.md) |

英文版本：[English Documentation](docs/documentation-index.md)

---

## 测试

```bash
# 完整测试套件
./scripts/check.sh

# 特定测试
uv run pytest tests/test_api.py -v
npm exec --yes pnpm@10 -- -C frontend test

# 评估状态
uv run ht --local /evals
```

---

## 部署

**自动部署**（通过 GitHub Actions）：
```bash
git push origin main
# 自动部署到生产环境
```

**手动部署**：
```bash
ssh hypertrade-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

---

## 贡献

1. 查看 `docs/contracts/` 了解当前冲刺范围
2. 行为变更时更新文档
3. 提交前运行 `./scripts/check.sh`
4. 提交到 `main` 分支
5. 推送触发自动部署

详见[开发者指南](docs/developer-guide.zh-CN.md)。

---

## 许可证

**私有仓库** - 保留所有权利。

仅供研究使用。不构成投资建议。

---

## 联系方式

- **文档**：[docs/documentation-index.md](docs/documentation-index.md)
- **问题**：通过仓库 Issue 追踪器提交

---

<div align="center">

**为系统化加密货币交易研究而构建**

[完整 README](README.md) • [文档中心](docs/documentation-index.md) • [用户手册](docs/user-manual.zh-CN.md)

</div>
