# HyperTrade

HyperTrade 是一个面向行情研究与执行的加密交易 Agent。它不在 BitPro 项目下开发，也不复用 BitPro 的 AI 研发/自主交易逻辑；BitPro 可以通过稳定 MCP/API 合同提供外部数据、策略生命周期、回测、模拟盘和交易状态能力，由 HyperTrade 封装成可审计工具。

> 本项目输出仅用于研究辅助，不构成任何投资建议。

## 当前 V1 能力

- Agent graph runtime：可观察的 intent、plan、approval、tool、reflect、report 节点。
- Provider Router：DeepSeek 默认，OpenAI/OpenRouter/Qwen chat 扩展位，CLI/API/前端可切换。
- Tool Call：行情、RAG、Memory、策略、回测、paper、live intent、Testnet execute。
- RAG：PostgreSQL/pgvector 兼容字段，citation-ready 命中。
- Memory：去重、tags、importance、confidence、usage audit；策略实验会沉淀 `strategy_knowledge` 记忆卡，并可聚合为策略库视图。
- 交易边界：Mainnet 执行阻断；OKX Testnet 可在审批和风控后 signed order。
- 策略工作流：研究、多版本回测证据、critique、下一实验建议、策略知识沉淀。
- BitPro MCP：健康检查、K 线直连、策略生成/创建/更新、BitPro 回测 job/result/artifact、模拟盘生命周期、监控快照和实盘持仓只读诊断入口。
- 可观测：`/harness`、CLI slash commands、deterministic eval suite。

## 技术栈

- Agent：LangGraph 思路的 AgentGraph/AgentKernel，显式 ToolRegistry、Trace、Memory、RAG。
- Backend：FastAPI、SQLAlchemy 2、Alembic、uv、pytest、ruff、mypy。
- Storage：PostgreSQL + pgvector。
- RAG：Qwen `text-embedding-v4` 配置位，V1 本地测试使用确定性 embedding fallback。
- LLM：DeepSeek 官方 API，默认 `deepseek-v4-flash`。
- Frontend：React、Vite、TypeScript、Tailwind、shadcn 风格组件、lucide-react。
- Deploy：Docker Compose、宿主机 Nginx、GitHub Actions self-hosted runner。

## CLI 常用命令

交互式 CLI 中，`/help` 会展示每条斜杠命令的用途，`/tools` 会展示每个 Agent 工具的分类、审批标记和功能说明。普通 Agent 提问在规划或工具执行期间会显示 `Thought` / `Thinking` 动态状态块；报告里的 Markdown 会渲染成更易读的标题、列表和表格。脚本需要原始 Markdown 时可设置 `HYPERTRADE_RENDERER=plain`。

```text
/status
/tools
/model deepseek
/rag 风控
/memory search 风控
/strategy library momentum_breakout_v1
/experiment 研究ETH趋势突破
/live intents
/live execute loi_...
/evals
```

## 文档地图

如果要了解项目状态，请从 `docs/README.md` 开始。实际操作和验证 Agent 能力时，读 `docs/knowledge/tool-usage-guide.md`；它按 Agent graph、Tool Call、Provider、RAG、Memory、策略知识、BitPro MCP、风控、Testnet 执行、CLI、前端、测试和部署 smoke 组织入口。

## 本地启动

```bash
cp .env.example .env
uv run pytest -q
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

前端默认访问 `http://localhost:3333`，后端默认 `http://localhost:3334`。

## 统一检查

```bash
./scripts/check.sh
```

## 目录

- `backend/`：FastAPI、Agent、Tool、RAG、Memory、行情采集。
- `frontend/`：React/Vite `/harness` 和行情摘要工作台。
- `docs/architecture/`：每个模块的中英双语架构说明。
- `docs/contracts/`：Sprint 合同。
- `deploy/`：Nginx 和服务器部署脚本。
