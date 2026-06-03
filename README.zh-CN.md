# HyperTrade

HyperTrade 是一个独立的 Agent 交易系统学习与作品项目。它不在 BitPro 项目下开发，也不复用 BitPro 的 AI 研发/自主交易逻辑；BitPro 只作为服务器部署方式和 OKX 环境变量形态参考。

> 本项目仅用于研究、学习和工程展示，不构成任何投资建议。

## 当前 V1 能力

- Agent graph runtime：可观察的 intent、plan、approval、tool、reflect、report 节点。
- Provider Router：DeepSeek 默认，OpenAI/OpenRouter/Qwen chat 扩展位，CLI/API/前端可切换。
- Tool Call：行情、RAG、Memory、策略、回测、paper、live intent、Testnet execute。
- RAG：PostgreSQL/pgvector 兼容字段，citation-ready 命中。
- Memory：去重、tags、importance、confidence、usage audit。
- 交易边界：Mainnet 执行阻断；OKX Testnet 可在审批和风控后 signed order。
- 策略工作流：研究、回测、critique、下一实验建议。
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

```text
/status
/model deepseek
/rag 风控
/memory search 风控
/experiment 研究ETH趋势突破
/live intents
/live execute loi_...
/evals
```

## 学习指南

如果想按 Agent 工具链学习代码，请从 `docs/knowledge/tool-usage-guide.md` 开始。它按 Agent graph、Tool Call、Provider、RAG、Memory、风控、Testnet 执行、CLI、前端、测试和部署 smoke 组织入口。

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
