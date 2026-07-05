# HyperTrade Developer Guide

## Table of Contents

- [Overview](#overview)
- [Development Environment Setup](#development-environment-setup)
- [Architecture Deep Dive](#architecture-deep-dive)
- [Adding New Tools](#adding-new-tools)
- [Adding New Providers](#adding-new-providers)
- [Adding Connectors](#adding-connectors)
- [Database Schema](#database-schema)
- [Testing](#testing)
- [Debugging](#debugging)
- [Deployment](#deployment)
- [Contributing](#contributing)

---

## Overview

This guide is for engineers extending HyperTrade with new tools, providers, connectors, evals, or deployment checks.

### Key Principles

1. **Tool Registry as Source of Truth**: All Agent-callable tools must be registered in `ToolRegistry`
2. **Policy-Driven Execution**: Tools declare scope, approval, idempotency requirements
3. **BitPro Boundary**: Never bypass BitPro MCP/API contracts or copy BitPro logic
4. **Evidence Over Inference**: Report missing data as unavailable, don't smooth over gaps
5. **Auditable Trace**: Every tool execution produces trace events
6. **Deterministic Evals**: Changes must not break existing eval cases

---

## Development Environment Setup

### Prerequisites

- Python 3.12+
- `uv` for Python package management
- Node.js 18+ and `pnpm` for frontend
- Docker and Docker Compose for local services
- PostgreSQL 14+ with pgvector extension (or SQLite for development)

### Local Setup

1. **Clone and Configure**:
   ```bash
   git clone git@github.com:Shadowell/HyperTrade.git
   cd HyperTrade
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

2. **Python Environment**:
   ```bash
   # uv automatically manages virtual environments
   uv sync
   ```

3. **Frontend Setup**:
   ```bash
   cd frontend
   npm exec --yes pnpm@10 install
   ```

4. **Database Setup**:
   
   **SQLite (quickstart)**:
   ```bash
   mkdir -p .local
   export DATABASE_URL="sqlite:///$(pwd)/.local/hypertrade.db"
   ```

   **PostgreSQL with Docker**:
   ```bash
   docker compose up -d postgres
   export DATABASE_URL="postgresql://hypertrade:hypertrade@localhost:5432/hypertrade"
   ```

5. **Run Migrations** (PostgreSQL):
   ```bash
   uv run alembic upgrade head
   ```

6. **Start Services**:
   
   Terminal 1 (Backend):
   ```bash
   uv run uvicorn hypertrade.main:app --app-dir backend/src --reload --host 0.0.0.0 --port 3334
   ```

   Terminal 2 (Frontend):
   ```bash
   npm exec --yes pnpm@10 -- -C frontend dev
   ```

   Terminal 3 (Worker, optional):
   ```bash
   uv run python -m hypertrade.worker
   ```

7. **Verify**:
   ```bash
   curl http://localhost:3334/api/health
   # Open http://localhost:3333/harness
   ```

---

## Architecture Deep Dive

### Component Layers

```
┌─────────────────────────────────────────────────┐
│  Client Layer (CLI, Web, API)                   │
├─────────────────────────────────────────────────┤
│  Agent Runtime (Kernel, Planner, Tool Executor) │
├─────────────────────────────────────────────────┤
│  Tool Registry & Risk Governance                │
├─────────────────────────────────────────────────┤
│  Services (Market, RAG, Memory, Strategy, etc.) │
├─────────────────────────────────────────────────┤
│  Data Layer (Database, OKX, BitPro)             │
└─────────────────────────────────────────────────┘
```

### Key Components

#### AgentKernel (`backend/src/hypertrade/agent/kernel.py`)

Orchestrates Agent runs:
- Accepts free-form prompts
- Delegates to chat provider for tool selection
- Executes tools through ToolRegistry
- Manages trace and report generation
- Implements graph-style runtime

**Key Methods**:
```python
def run_chat(self, prompt: str) -> CompletedAgentRun:
    """Execute a chat-style Agent run."""
    
def get_run(self, run_id: str) -> CompletedAgentRun:
    """Retrieve a completed run by ID."""
```

#### ToolRegistry (`backend/src/hypertrade/tools/registry.py`)

Metadata catalog for all Agent tools:
- Tool schemas and descriptions
- Policy metadata (scope, approval, idempotency)
- Source-of-truth declarations
- Connector origins

**Adding a Tool**:
```python
ToolDefinition(
    name="my_tool.action",
    description="What this tool does",
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

Manages chat provider selection and model routing:
- Vide Coding (opus-4.6)
- DeepSeek
- OpenAI-compatible
- Codex
- OpenRouter
- Qwen (extensible)

**Adding a Provider**:
1. Implement provider client in `providers/`
2. Add to `ProviderRuntime.list_providers()`
3. Handle in `ProviderRuntime.get_chat_model()`

#### RiskGovernancePolicy (`backend/src/hypertrade/risk/policy.py`)

Enforces tool execution policies:
- Scope checks (read vs write)
- Approval requirements
- Idempotency validation
- Trace policy decisions

---

## Adding New Tools

### Step 1: Define the Tool Function

Create the tool implementation in the appropriate service module.

**Example** (`backend/src/hypertrade/market/intelligence.py`):
```python
from dataclasses import dataclass

@dataclass
class MarketIntelligenceResult:
    """Market intelligence aggregation."""
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
    """Aggregate multi-source market intelligence."""
    # Implementation
    pass
```

### Step 2: Register in ToolRegistry

Add to `ToolRegistry.default()` in `backend/src/hypertrade/tools/registry.py`:

```python
ToolDefinition(
    name="market.intelligence",
    description="Multi-source market intelligence with funding and open interest.",
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

### Step 3: Wire into AgentKernel

Add tool execution case in `AgentKernel._execute_tool()`:

```python
def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # ... existing tools ...
    
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

### Step 4: Add Function Calling Schema

Update the planner prompt with the tool schema in `AgentKernel._plan()`:

```python
tools = [
    # ... existing tools ...
    {
        "type": "function",
        "function": {
            "name": "market_intelligence",
            "description": "Get multi-source market intelligence including funding rates and open interest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Symbol to query (e.g., BTC, ETH)"
                    },
                    "include_funding": {
                        "type": "boolean",
                        "description": "Include funding rate data"
                    },
                    "include_oi": {
                        "type": "boolean",
                        "description": "Include open interest data"
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]
```

### Step 5: Add Tests

Create eval cases in `backend/tests/test_agent_eval_suite.py`:

```python
def test_eval_market_intelligence_tool_selection():
    """Verify market intelligence prompts route to the correct tool."""
    suite = AgentEvalSuite()
    result = suite.run_eval("market_intelligence_tool_selection")
    assert result["status"] == "pass"
    assert "market_intelligence" in result["tools_called"]
```

### Step 6: Document

Add to `docs/knowledge/tool-usage-guide.md`:

```markdown
### market_intelligence

**Purpose**: Aggregate multi-source market intelligence.

**Usage**:
CLI: `获取 BTC 的市场情报`
API: Agent tool call with `{"symbol": "BTC"}`

**Returns**:
- Funding rates
- Open interest
- Curated market context
- Provenance metadata
- Missing field disclosure
```

---

## Adding New Providers

### Step 1: Create Provider Client

Create a new provider module in `backend/src/hypertrade/providers/`:

**Example** (`my_provider.py`):
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
        """Send chat completion request."""
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

### Step 2: Add to ProviderRuntime

Update `backend/src/hypertrade/providers/runtime.py`:

```python
def list_providers(
    self,
    selected: str = "",
    selected_models: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    providers = [
        # ... existing providers ...
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
    # ... existing providers ...
```

### Step 3: Add Configuration

Update `backend/src/hypertrade/config.py`:

```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    my_provider_api_key: str = ""
    my_provider_base_url: str = "https://api.myprovider.com"
```

Update `.env.example`:
```bash
MY_PROVIDER_API_KEY=
MY_PROVIDER_BASE_URL=https://api.myprovider.com
```

### Step 4: Test

Add provider tests in `backend/tests/test_provider_runtime.py`:

```python
def test_my_provider_configured():
    settings = Settings(my_provider_api_key="test-key")
    runtime = ProviderRuntime(settings)
    providers = runtime.list_providers()
    my_provider = next(p for p in providers if p["name"] == "my_provider")
    assert my_provider["configured"] is True
```

---

## Adding Connectors

Connectors expose external system capabilities to HyperTrade.

### Step 1: Define Connector

Create in `backend/src/hypertrade/connectors/`:

**Example** (`my_connector.py`):
```python
from dataclasses import dataclass

@dataclass
class MyConnectorCapabilities:
    """Capabilities exposed by My Connector."""
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
    """Discover My Connector capabilities."""
    return MyConnectorCapabilities(
        configured=bool(settings.my_connector_url),
        base_url=settings.my_connector_url,
        auth_configured=bool(settings.my_connector_token),
        tool_groups=["data", "execution"],
        available_tools=["data_fetch", "order_submit"],
    )
```

### Step 2: Register in ConnectorRegistry

Update `backend/src/hypertrade/connectors/registry.py`:

```python
def default(cls, settings: Settings) -> "ConnectorRegistry":
    return cls(
        connectors=[
            # ... existing connectors ...
            my_connector_capabilities(settings),
        ]
    )
```

### Step 3: Add Connector Tools

Register connector tools in ToolRegistry with `connector_origin`:

```python
ToolDefinition(
    name="my_connector.data_fetch",
    description="Fetch data from My Connector",
    category="connector",
    connector_origin={
        "connector_id": "my_connector",
        "tool": "data_fetch"
    }
)
```

---

## Database Schema

### Core Tables

**agent_runs**: Agent execution records
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

**trace_events**: Tool execution trace
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

**market_tickers**: OKX ticker snapshots
```sql
CREATE TABLE market_tickers (
    inst_id TEXT PRIMARY KEY,
    last NUMERIC,
    volume_ccy_24h NUMERIC,
    change_utc0_pct NUMERIC,
    updated_at TIMESTAMP NOT NULL
);
```

**memory_items**: Audited memory records
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

**rag_documents** and **rag_chunks**: Knowledge retrieval
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

### Adding New Tables

1. **Create Migration**:
   ```bash
   uv run alembic revision -m "Add my_new_table"
   ```

2. **Define Schema** in generated migration file:
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

3. **Add ORM Model** in `backend/src/hypertrade/db.py`:
   ```python
   class MyNewTable(Base):
       __tablename__ = "my_new_table"
       
       id: Mapped[str] = mapped_column(Text, primary_key=True)
       data: Mapped[str | None] = mapped_column(Text)
       created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
   ```

4. **Run Migration**:
   ```bash
   uv run alembic upgrade head
   ```

---

## Testing

### Test Structure

```
tests/
├── test_api.py                  # API endpoint tests
├── test_agent_eval_suite.py     # Agent evaluation tests
├── test_agent_market_summary.py # Market tool tests
├── test_tool_registry.py        # Tool policy tests
├── test_provider_runtime.py     # Provider tests
└── fixtures/                    # Test data
```

### Running Tests

**All tests**:
```bash
./scripts/check.sh
```

**Specific tests**:
```bash
uv run pytest tests/test_api.py -v
uv run pytest tests/test_agent_eval_suite.py::test_eval_tool_choice_market_summary -v
```

**With coverage**:
```bash
uv run pytest --cov=hypertrade --cov-report=html
```

### Writing Eval Cases

Evals guard against regressions. Add to `AgentEvalSuite`:

```python
def _eval_my_new_feature(self) -> EvalResult:
    """Test my new feature."""
    kernel = AgentKernel(
        self.db,
        knowledge_dir="docs/knowledge",
        settings=self.settings,
    )
    
    run = kernel.run_chat("Test prompt for my feature")
    
    # Assertions
    assert run.status == "completed"
    assert "expected_tool" in [t["tool"] for t in run.trace]
    assert "expected_keyword" in run.report.lower()
    
    return EvalResult(
        eval_id="my_new_feature",
        status="pass",
        message="Feature works correctly"
    )
```

Register in `AgentEvalSuite.run_all()`:
```python
results.append(self._eval_my_new_feature())
```

---

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Inspect Trace Events

**CLI**:
```bash
# After a run
/runs
# Select a run ID
/run <run_id>
```

**API**:
```bash
curl http://localhost:3334/api/agent/runs/<run_id>
```

**Database**:
```sql
SELECT * FROM trace_events WHERE run_id = 'run_abc123' ORDER BY created_at;
```

### Debug Provider Issues

Add logging to provider calls:
```python
logger.debug(f"Provider request: {messages}")
response = client.chat(messages=messages, tools=tools)
logger.debug(f"Provider response: {response}")
```

### Test Tool Execution Directly

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

## Deployment

### Production Deployment

HyperTrade deploys via GitHub Actions to a self-hosted runner.

**Deployment Flow**:
1. Push to `main` branch
2. GitHub Actions triggers `.github/workflows/deploy.yml`
3. Self-hosted runner (label: `hypertrade-production`) runs deployment
4. `deploy/deploy.sh` pulls code, builds images, restarts services
5. Deployment SHA recorded in `/opt/hypertrade/deploy/last_deployed_sha`

**Manual Deployment**:
```bash
ssh hypertrade-server
cd /opt/hypertrade
sudo -u hypertrade ./deploy/deploy.sh
```

### Server Setup

**Bootstrap server** (one-time):
```bash
sudo ./deploy/setup-server.sh
sudo install -m 600 .env.example /opt/hypertrade/.env
sudo editor /opt/hypertrade/.env
```

**Deployment verification**:
```bash
curl -fsS http://localhost:3334/api/health
curl -fsS http://localhost:3333/api/health  # via Nginx
hypertrade ask "看下ETH行情"
```

### Docker Compose Services

- `api`: FastAPI backend
- `frontend`: Vite production build served by Nginx
- `postgres`: PostgreSQL with pgvector
- `worker`: Background jobs (optional)

**Service management**:
```bash
docker compose ps
docker compose logs -f api
docker compose restart api
docker compose down && docker compose up -d
```

---

## Contributing

### Development Workflow

1. **Read Contracts**: Check `docs/contracts/` for active sprint scope
2. **Stay in Scope**: Keep changes within the current sprint contract
3. **Update Docs**: Update architecture/knowledge docs when behavior changes
4. **Run Tests**: Run `./scripts/check.sh` before committing
5. **Commit**: Commit to `main` branch (no feature branches in current workflow)
6. **Deploy**: Push triggers automatic deployment
7. **Smoke Test**: Verify production health after deployment

### Code Style

**Python**:
- Format with `ruff format`
- Lint with `ruff check`
- Type check with `mypy`

**TypeScript/React**:
- Lint with `pnpm lint`
- Format with Prettier (via ESLint)

**Run all checks**:
```bash
./scripts/check.sh
```

### Documentation Standards

- **Architecture docs**: Module-level design in `docs/architecture/`
- **Contracts**: Sprint scope and delivery in `docs/contracts/`
- **Knowledge**: Operator guides in `docs/knowledge/`
- **Runbooks**: Operational procedures in `docs/runbooks/`

**When to document**:
- New tools, providers, connectors
- API changes
- Policy changes
- Operational procedures
- Architecture decisions

**When NOT to document**:
- Implementation details visible in code
- Temporary workarounds
- Chat history or debug notes
- Redundant information already in code

### Commit Messages

Keep commit messages concise and descriptive:

```
Implement Sprint 74 portfolio scheduler

Add world model portfolio scheduler with defensive action
execution gate and schedule persistence.
```

Avoid:
- Generic messages ("update", "fix")
- Overly detailed implementation notes
- Copy-pasted chat history

---

## Additional Resources

- **API Reference**: [api-reference.md](api-reference.md)
- **User Manual**: [user-manual.md](user-manual.md)
- **Architecture**: [architecture/](architecture/)
- **Knowledge Base**: [knowledge/](knowledge/)
- **Runbooks**: [runbooks/](runbooks/)
- **Project Spec**: [spec.md](spec.md)
- **Progress Log**: [progress.md](progress.md)

---

## Getting Help

For questions or issues:
1. Check existing documentation in `docs/`
2. Review architecture notes in `docs/architecture/`
3. Check runbooks for operational issues
4. Submit issues to the repository

---

## Next Steps

- Review [Architecture Diagram](architecture/19-hypertrade-architecture-diagram.md)
- Explore [Tool Calling Design](architecture/04-tool-calling.md)
- Read [Agent Graph Runtime](architecture/12-agent-graph-langgraph-runtime.md)
- Study [Risk Engine](architecture/14-risk-engine.md)
- Examine [Eval Suite](testing/agent-eval-suite.md)
