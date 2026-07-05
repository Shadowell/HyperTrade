# HyperTrade 开发者指南

## 目录

- [概述](#概述)
- [开发环境搭建](#开发环境搭建)
- [架构深度剖析](#架构深度剖析)
- [添加新工具](#添加新工具)
- [添加新提供者](#添加新提供者)
- [添加连接器](#添加连接器)
- [数据库架构](#数据库架构)
- [测试](#测试)
- [调试](#调试)
- [部署](#部署)
- [贡献指南](#贡献指南)

---

## 概述

本指南面向需要扩展 HyperTrade 的工程师，包括添加新工具、提供者、连接器、评估或部署检查。

### 核心原则

1. **工具注册表是真理源**：所有 Agent 可调用的工具必须在 `ToolRegistry` 中注册
2. **策略驱动执行**：工具声明其范围、批准和幂等性要求
3. **BitPro 边界**：永远不要绕过 BitPro MCP/API 契约或复制 BitPro 逻辑
4. **证据优于推断**：将缺失的数据报告为不可用，不要掩盖数据缺口
5. **可审计追踪**：每次工具执行都产生追踪事件
6. **确定性评估**：变更不得破坏现有的评估用例

---

## 开发环境搭建

### 前置条件

- Python 3.12+
- `uv` 用于 Python 包管理
- Node.js 18+ 和 `pnpm` 用于前端
- Docker 和 Docker Compose 用于本地服务
- PostgreSQL 14+ 带 pgvector 扩展（或使用 SQLite 进行开发）

### 本地搭建

1. **克隆并配置**：
   ```bash
   git clone git@github.com:Shadowell/HyperTrade.git
   cd HyperTrade
   cp .env.example .env
   # 编辑 .env 填入你的 API 密钥和配置
   ```

2. **Python 环境**：
   ```bash
   # uv 自动管理虚拟环境
   uv sync
   ```

3. **前端设置**：
   ```bash
   cd frontend
   npm exec --yes pnpm@10 install
   ```

4. **数据库设置**：
   
   **SQLite（快速启动）**：
   ```bash
   mkdir -p .local
   export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
   ```

   **PostgreSQL（使用 Docker）**：
   ```bash
   docker compose up -d postgres
   export DATABASE_URL="postgresql://hypertrade:hypertrade@localhost:5432/hypertrade"
   ```

5. **运行迁移**（PostgreSQL）：
   ```bash
   uv run alembic upgrade head
   ```

6. **启动服务**：
   
   终端 1（后端）：
   ```bash
   uv run uvicorn hypertrade.main:app --app-dir backend/src --reload --host 0.0.0.0 --port 3334
   ```

   终端 2（前端）：
   ```bash
   npm exec --yes pnpm@10 -- -C frontend dev
   ```

   终端 3（Worker，可选）：
   ```bash
   uv run python -m hypertrade.worker
   ```

7. **验证**：
   ```bash
   curl http://localhost:3334/api/health
   # 打开 http://localhost:3333/harness
   ```

---

## 架构深度剖析

### 组件层次

```
┌─────────────────────────────────────────────────┐
│  客户端层 (CLI, Web, API)                        │
├─────────────────────────────────────────────────┤
│  Agent 运行时 (Kernel, Planner, Tool Executor)  │
├─────────────────────────────────────────────────┤
│  工具注册表与风控治理                            │
├─────────────────────────────────────────────────┤
│  服务层 (Market, RAG, Memory, Strategy, 等)     │
├─────────────────────────────────────────────────┤
│  数据层 (Database, OKX, BitPro)                  │
└─────────────────────────────────────────────────┘
```

### 核心组件

#### AgentKernel (`backend/src/hypertrade/agent/kernel.py`)

编排 Agent 运行：
- 接受自由形式的提示
- 委托给聊天提供者进行工具选择
- 通过 ToolRegistry 执行工具
- 管理追踪和报告生成
- 实现图式运行时

**关键方法**：
```python
def run_chat(self, prompt: str) -> CompletedAgentRun:
    """执行聊天式 Agent 运行。"""
    
def get_run(self, run_id: str) -> CompletedAgentRun:
    """通过 ID 检索已完成的运行。"""
```

#### ToolRegistry (`backend/src/hypertrade/tools/registry.py`)

所有 Agent 工具的元数据目录：
- 工具架构和描述
- 策略元数据（范围、批准、幂等性）
- 真理源声明
- 连接器来源

**添加工具**：
```python
ToolDefinition(
    name="my_tool.action",
    description="此工具的功能",
    category="my_category",
    requires_approval=False,
    policy=ToolPolicy(
        scope="read",
        approval="none",
        idempotency="not_required",
        source_of_truth="hypertrade_db",
        timeout_class="standard",
        safe_sample_limit=100,
    )
)
```

#### ProviderRuntime (`backend/src/hypertrade/providers/runtime.py`)

管理聊天提供者选择和模型路由：
- DeepSeek（默认）
- OpenAI 兼容
- Codex
- OpenRouter
- Qwen（可扩展）

**添加提供者**：
1. 在 `providers/` 中实现提供者客户端
2. 添加到 `ProviderRuntime.list_providers()`
3. 在 `ProviderRuntime.get_chat_model()` 中处理

#### RiskGovernancePolicy (`backend/src/hypertrade/risk/policy.py`)

强制执行工具执行策略：
- 范围检查（读 vs 写）
- 批准要求
- 幂等性验证
- 追踪策略决策

---

## 添加新工具

### 步骤 1：定义工具函数

在适当的服务模块中创建工具实现。

**示例** (`backend/src/hypertrade/market/intelligence.py`)：
```python
from dataclasses import dataclass

@dataclass
class MarketIntelligenceResult:
    """市场情报聚合。"""
    funding_rates: dict[str, str]
    open_interest: dict[str, str]
    curated_context: str
    provenance: dict[str, str]
    freshness_seconds: int
    missing_fields: list[str]

def get_market_intelligence(
    symbol: str,
    include_funding: bool = True,
    include_oi: bool = True,
) -> MarketIntelligenceResult:
    """聚合多源市场情报。"""
    # 实现
    pass
```

### 步骤 2：在 ToolRegistry 中注册

在 `backend/src/hypertrade/tools/registry.py` 的 `ToolRegistry.default()` 中添加：

```python
ToolDefinition(
    name="market.intelligence",
    description="多源市场情报，包括资金费率和持仓量。",
    category="market",
    requires_approval=False,
    policy=ToolPolicy(
        scope="read",
        source_of_truth="okx_public_api",
        timeout_class="standard",
        safe_sample_limit=50,
    )
)
```

### 步骤 3：连接到 AgentKernel

在 `AgentKernel._execute_tool()` 中添加工具执行用例：

```python
def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # ... 现有工具 ...
    
    elif tool_name == "market_intelligence":
        symbol = str(arguments.get("symbol", "BTC"))
        result = get_market_intelligence(
            symbol=symbol,
            include_funding=arguments.get("include_funding", True),
            include_oi=arguments.get("include_oi", True),
        )
        return {
            "symbol": symbol,
            "funding_rates": result.funding_rates,
            "open_interest": result.open_interest,
            "curated_context": result.curated_context,
            "provenance": result.provenance,
            "freshness_seconds": result.freshness_seconds,
            "missing_fields": result.missing_fields,
        }
```

### 步骤 4：添加函数调用架构

在 `AgentKernel._plan()` 中更新规划器提示，添加工具架构：

```python
tools = [
    # ... 现有工具 ...
    {
        "type": "function",
        "function": {
            "name": "market_intelligence",
            "description": "获取包括资金费率和持仓量的多源市场情报。",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "要查询的币种（如 BTC、ETH）"
                    },
                    "include_funding": {
                        "type": "boolean",
                        "description": "包括资金费率数据"
                    },
                    "include_oi": {
                        "type": "boolean",
                        "description": "包括持仓量数据"
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]
```

### 步骤 5：添加测试

在 `backend/tests/test_agent_eval_suite.py` 中创建评估用例：

```python
def test_eval_market_intelligence_tool_selection():
    """验证市场情报提示路由到正确的工具。"""
    suite = AgentEvalSuite()
    result = suite.run_eval("market_intelligence_tool_selection")
    assert result["status"] == "pass"
    assert "market_intelligence" in result["tools_called"]
```

### 步骤 6：文档化

添加到 `docs/knowledge/tool-usage-guide.md`：

```markdown
### market_intelligence

**用途**：聚合多源市场情报。

**使用方法**：
CLI: `获取 BTC 的市场情报`
API: Agent 工具调用，参数 `{"symbol": "BTC"}`

**返回**：
- 资金费率
- 持仓量
- 精选市场上下文
- 来源元数据
- 缺失字段披露
```

---

## 添加新提供者

### 步骤 1：创建提供者客户端

在 `backend/src/hypertrade/providers/` 中创建新的提供者模块：

**示例** (`my_provider.py`)：
```python
from typing import Any
import httpx

class MyProviderClient:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.client = httpx.Client(timeout=30.0)
    
    def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        model: str = "default-model",
    ) -> dict[str, Any]:
        """发送聊天完成请求。"""
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "tools": tools or [],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        return response.json()
```

### 步骤 2：添加到 ProviderRuntime

更新 `backend/src/hypertrade/providers/runtime.py`：

```python
def list_providers(
    self,
    selected: str = "",
    selected_models: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    providers = [
        # ... 现有提供者 ...
        {
            "name": "my_provider",
            "display_name": "My Provider",
            "configured": bool(self.settings.my_provider_api_key),
            "selected": selected == "my_provider",
            "model": selected_models.get("my_provider", ""),
            "available_models": ["model-v1", "model-v2"],
        }
    ]
    return providers

def get_chat_model(
    self,
    provider: str | None = None,
    model_override: str | None = None,
) -> Any:
    provider = provider or self.settings.active_chat_provider
    
    if provider == "my_provider":
        return MyProviderClient(
            api_key=self.settings.my_provider_api_key,
            base_url=self.settings.my_provider_base_url,
        )
    # ... 现有提供者 ...
```

### 步骤 3：添加配置

更新 `backend/src/hypertrade/config.py`：

```python
class Settings(BaseSettings):
    # ... 现有设置 ...
    
    my_provider_api_key: str = ""
    my_provider_base_url: str = "https://api.myprovider.com"
```

更新 `.env.example`：
```bash
MY_PROVIDER_API_KEY=
MY_PROVIDER_BASE_URL=https://api.myprovider.com
```

### 步骤 4：测试

在 `backend/tests/test_provider_runtime.py` 中添加提供者测试：

```python
def test_my_provider_configured():
    settings = Settings(my_provider_api_key="test-key")
    runtime = ProviderRuntime(settings)
    providers = runtime.list_providers()
    my_provider = next(p for p in providers if p["name"] == "my_provider")
    assert my_provider["configured"] is True
```

---

## 添加连接器

连接器向 HyperTrade 公开外部系统能力。

### 步骤 1：定义连接器

在 `backend/src/hypertrade/connectors/` 中创建：

**示例** (`my_connector.py`)：
```python
from dataclasses import dataclass

@dataclass
class MyConnectorCapabilities:
    """My Connector 公开的能力。"""
    connector_id: str = "my_connector"
    name: str = "My External Service"
    configured: bool = False
    base_url: str = ""
    auth_configured: bool = False
    tool_groups: list[str] = None
    available_tools: list[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "name": self.name,
            "configured": self.configured,
            "base_url": self.base_url,
            "auth_configured": self.auth_configured,
            "tool_groups": self.tool_groups or [],
            "available_tools": self.available_tools or [],
        }

def my_connector_capabilities(settings: Settings) -> MyConnectorCapabilities:
    """发现 My Connector 能力。"""
    return MyConnectorCapabilities(
        configured=bool(settings.my_connector_url),
        base_url=settings.my_connector_url,
        auth_configured=bool(settings.my_connector_token),
        tool_groups=["data", "execution"],
        available_tools=["data_fetch", "order_submit"],
    )
```

### 步骤 2：在 ConnectorRegistry 中注册

更新 `backend/src/hypertrade/connectors/registry.py`：

```python
def default(cls, settings: Settings) -> "ConnectorRegistry":
    return cls(
        connectors=[
            # ... 现有连接器 ...
            my_connector_capabilities(settings),
        ]
    )
```

### 步骤 3：添加连接器工具

在 ToolRegistry 中注册连接器工具，带有 `connector_origin`：

```python
ToolDefinition(
    name="my_connector.data_fetch",
    description="从 My Connector 获取数据",
    category="connector",
    connector_origin={
        "connector_id": "my_connector",
        "tool": "data_fetch"
    }
)
```

---

## 数据库架构

### 核心表

**agent_runs**：Agent 执行记录
```sql
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    report TEXT,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);
```

**trace_events**：工具执行追踪
```sql
CREATE TABLE trace_events (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES agent_runs(id),
    event_type TEXT NOT NULL,
    tool_name TEXT,
    payload JSONB,
    created_at TIMESTAMP NOT NULL
);
```

**market_tickers**：OKX 行情快照
```sql
CREATE TABLE market_tickers (
    inst_id TEXT PRIMARY KEY,
    last NUMERIC,
    volume_ccy_24h NUMERIC,
    change_utc0_pct NUMERIC,
    updated_at TIMESTAMP NOT NULL
);
```

**memory_items**：审计的 Memory 记录
```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT[],
    confidence REAL,
    importance REAL,
    disabled BOOLEAN DEFAULT FALSE,
    usage_count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);
```

**rag_documents** 和 **rag_chunks**：知识检索
```sql
CREATE TABLE rag_documents (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    content_hash TEXT NOT NULL,
    scanned_at TIMESTAMP NOT NULL
);

CREATE TABLE rag_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT REFERENCES rag_documents(id),
    content TEXT NOT NULL,
    embedding VECTOR(1024),  -- pgvector
    metadata JSONB
);
```

### 添加新表

1. **创建迁移**：
   ```bash
   uv run alembic revision -m "Add my_new_table"
   ```

2. **在生成的迁移文件中定义架构**：
   ```python
   def upgrade():
       op.create_table(
           'my_new_table',
           sa.Column('id', sa.Text(), nullable=False),
           sa.Column('data', sa.Text(), nullable=True),
           sa.Column('created_at', sa.DateTime(), nullable=False),
           sa.PrimaryKeyConstraint('id')
       )
   ```

3. **在 `backend/src/hypertrade/db.py` 中添加 ORM 模型**：
   ```python
   class MyNewTable(Base):
       __tablename__ = "my_new_table"
       
       id: Mapped[str] = mapped_column(Text, primary_key=True)
       data: Mapped[str | None] = mapped_column(Text)
       created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
   ```

4. **运行迁移**：
   ```bash
   uv run alembic upgrade head
   ```

---

## 测试

### 测试结构

```
tests/
├── test_api.py                  # API 端点测试
├── test_agent_eval_suite.py     # Agent 评估测试
├── test_agent_market_summary.py # 市场工具测试
├── test_tool_registry.py        # 工具策略测试
├── test_provider_runtime.py     # 提供者测试
└── fixtures/                    # 测试数据
```

### 运行测试

**所有测试**：
```bash
./scripts/check.sh
```

**特定测试**：
```bash
uv run pytest tests/test_api.py -v
uv run pytest tests/test_agent_eval_suite.py::test_eval_tool_choice_market_summary -v
```

**带覆盖率**：
```bash
uv run pytest --cov=hypertrade --cov-report=html
```

### 编写评估用例

评估用于防止回归。添加到 `AgentEvalSuite`：

```python
def _eval_my_new_feature(self) -> EvalResult:
    """测试我的新功能。"""
    kernel = AgentKernel(
        self.db,
        knowledge_dir="docs/knowledge",
        settings=self.settings,
    )
    
    run = kernel.run_chat("测试我的新功能的提示")
    
    # 断言
    assert run.status == "completed"
    assert "expected_tool" in [t["tool"] for t in run.trace]
    assert "expected_keyword" in run.report.lower()
    
    return EvalResult(
        eval_id="my_new_feature",
        status="pass",
        message="功能正常工作"
    )
```

在 `AgentEvalSuite.run_all()` 中注册：
```python
results.append(self._eval_my_new_feature())
```

---

## 调试

### 启用调试日志

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 检查追踪事件

**CLI**：
```bash
# 运行后
/runs
# 选择一个 run ID
/run <run_id>
```

**API**：
```bash
curl http://localhost:3334/api/agent/runs/<run_id>
```

**数据库**：
```sql
SELECT * FROM trace_events WHERE run_id = 'run_abc123' ORDER BY created_at;
```

### 调试提供者问题

在提供者调用中添加日志：
```python
logger.debug(f"Provider request: {messages}")
response = client.chat(messages=messages, tools=tools)
logger.debug(f"Provider response: {response}")
```

### 直接测试工具执行

```python
from hypertrade.agent.kernel import AgentKernel
from hypertrade.db import Database
from hypertrade.config import get_settings

db = Database("sqlite:///:memory:")
db.create_all()
settings = get_settings()

kernel = AgentKernel(db, "docs/knowledge", settings)
result = kernel._execute_tool("market.ticker", {"symbol": "BTC"})
print(result)
```

---

## 部署

### 生产部署

HyperTrade 通过 GitHub Actions 部署到自托管运行器。

**部署流程**：
1. 推送到 `main` 分支
2. GitHub Actions 触发 `.github/workflows/deploy.yml`
3. 自托管运行器（标签：`hypertrade-production`）运行部署
4. `deploy/deploy.sh` 拉取代码、构建镜像、重启服务
5. 部署 SHA 记录在 `/opt/hypertrade/deploy/last_deployed_sha`

**手动部署**：
```bash
ssh hypertrade-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

### 服务器设置

**引导服务器**（一次性）：
```bash
sudo ./deploy/setup-server.sh
sudo install -m 600 .env.example /opt/hypertrade/.env
sudo editor /opt/hypertrade/.env
```

**部署验证**：
```bash
curl -fsS http://localhost:3334/api/health
curl -fsS http://localhost:3333/api/health  # 通过 Nginx
hypertrade ask "看下ETH行情"
```

### Docker Compose 服务

- `api`：FastAPI 后端
- `frontend`：Vite 生产构建，由 Nginx 提供服务
- `postgres`：带 pgvector 的 PostgreSQL
- `worker`：后台作业（可选）

**服务管理**：
```bash
docker compose ps
docker compose logs -f api
docker compose restart api
docker compose down && docker compose up -d
```

---

## 贡献指南

### 开发工作流

1. **阅读合约**：检查 `docs/contracts/` 中的活动冲刺范围
2. **保持在范围内**：将更改保持在当前冲刺合约内
3. **更新文档**：当行为改变时更新架构/知识文档
4. **运行测试**：提交前运行 `./scripts/check.sh`
5. **提交**：提交到 `main` 分支（当前工作流中无特性分支）
6. **部署**：推送触发自动部署
7. **冒烟测试**：部署后验证生产健康状态

### 代码风格

**Python**：
- 使用 `ruff format` 格式化
- 使用 `ruff check` 检查
- 使用 `mypy` 类型检查

**TypeScript/React**：
- 使用 `pnpm lint` 检查
- 通过 ESLint 使用 Prettier 格式化

**运行所有检查**：
```bash
./scripts/check.sh
```

### 文档标准

- **架构文档**：`docs/architecture/` 中的模块级设计
- **合约**：`docs/contracts/` 中的冲刺范围和交付
- **知识**：`docs/knowledge/` 中的操作指南
- **运行手册**：`docs/runbooks/` 中的操作程序

**何时编写文档**：
- 新工具、提供者、连接器
- API 更改
- 策略更改
- 操作程序
- 架构决策

**何时不编写文档**：
- 代码中可见的实现细节
- 临时解决方法
- 聊天历史或调试笔记
- 代码中已有的冗余信息

### 提交消息

保持提交消息简洁和描述性：

```
实现 Sprint 74 投资组合调度器

添加带防御性操作执行门禁和调度持久化的世界模型
投资组合调度器。
```

避免：
- 通用消息（"更新"、"修复"）
- 过于详细的实现说明
- 复制粘贴的聊天历史

---

## 其他资源

- **API 参考**：[api-reference.zh-CN.md](api-reference.zh-CN.md)
- **用户手册**：[user-manual.zh-CN.md](user-manual.zh-CN.md)
- **架构**：[architecture/](architecture/)
- **知识库**：[knowledge/](knowledge/)
- **运行手册**：[runbooks/](runbooks/)
- **项目规格**：[spec.md](spec.md)
- **进度日志**：[progress.md](progress.md)

---

## 获取帮助

如有问题或疑问：
1. 检查 `docs/` 中的现有文档
2. 查看 `docs/architecture/` 中的架构说明
3. 检查运行手册中的操作问题
4. 向仓库提交 Issue

---

## 下一步

- 查看[架构图](architecture/19-hypertrade-architecture-diagram.md)
- 探索[工具调用设计](architecture/04-tool-calling.md)
- 阅读 [Agent 图式运行时](architecture/12-agent-graph-langgraph-runtime.md)
- 研究[风控引擎](architecture/14-risk-engine.md)
- 检查[评估套件](testing/agent-eval-suite.md)
