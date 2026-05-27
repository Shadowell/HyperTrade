# HyperTrade

HyperTrade 是一个独立的 Agent 交易系统学习与作品项目。它不在 BitPro 项目下开发，也不复用 BitPro 的 AI 研发/自主交易逻辑；BitPro 只作为服务器部署方式和 OKX 环境变量形态参考。

> 本项目仅用于研究、学习和工程展示，不构成任何投资建议。

## Sprint 01

第一轮只跑通一条主闭环：

- OKX 全市场永续合约 `SWAP` 行情采集。
- WebSocket tickers 为主，REST 作为 instruments/funding/OI/K 线补充和降级。
- 用户在自由聊天中按需发起行情归纳。
- Agent 运行过程中记录 Tool Call、RAG 命中、Memory 写入和 trace。
- 前端提供 `/harness` 和行情摘要页。

## 技术栈

- Agent：LangGraph 思路的 AgentKernel，显式 ToolRegistry、Trace、Memory、RAG。
- Backend：FastAPI、SQLAlchemy 2、Alembic、uv、pytest、ruff、mypy。
- Storage：PostgreSQL + pgvector。
- RAG：Qwen `text-embedding-v4` 配置位，V1 本地测试使用确定性 embedding fallback。
- LLM：DeepSeek 官方 API，默认 `deepseek-v4-flash`。
- Frontend：React、Vite、TypeScript、Tailwind、shadcn 风格组件、lucide-react。
- Deploy：Docker Compose、宿主机 Nginx、GitHub Actions self-hosted runner。

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

