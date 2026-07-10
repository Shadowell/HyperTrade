# 优化计划 1：结构化日志 + OpenTelemetry 可观测性

## 现状诊断

- **零生产日志**：`main.py` 没有 `import logging`，端点错误只通过 `HTTPException` 返回
- **唯一观测手段是 DB 审计**：`TraceEvent` 表记录工具调用轨迹，只能做事后审计
- **LLM 调用无追踪**：provider 选择、token 消耗、响应延迟、planning 轮次全无记录
- **工具执行无耗时统计**：`kernel.py` 的工具 dispatch 无性能埋点
- **provider 静默失败**：`runtime.py` 中未配置的 provider 返回 `None` 且不打印任何日志

## 目标

引入 `structlog`（结构化日志）+ `opentelemetry`（分布式追踪），形成三层可观测体系：

| 层级 | 方案 | 用途 |
|------|------|------|
| **日志** | structlog | 所有关键路径的结构化日志，JSON 输出 |
| **追踪** | OpenTelemetry (ConsoleExporter) | Agent 全链路 trace |
| **指标** | prometheus-client | 请求量、延迟、Agent 成功率 |

## 涉及文件

| 操作 | 文件 |
|------|------|
| 新建 | `backend/src/hypertrade/logging_config.py` |
| 新建 | `backend/src/hypertrade/telemetry.py` |
| 改造 | `backend/src/hypertrade/main.py` |
| 改造 | `backend/src/hypertrade/agent/kernel.py` |
| 改造 | `backend/src/hypertrade/agent/planner.py` |
| 改造 | `backend/src/hypertrade/providers/runtime.py` |
| 改造 | `backend/src/hypertrade/providers/chat.py` |
| 改造 | `backend/src/hypertrade/market/client.py` |
| 改造 | `pyproject.toml` |

---

## 实施步骤

### Phase 1：structlog 集成（核心路径）

#### 步骤 1.1：新建 `backend/src/hypertrade/logging_config.py`

```python
import logging
import structlog

from hypertrade.config import Settings


def configure_logging(settings: Settings) -> None:
    """Configure structlog with JSON output to stdout."""
    shared_processors = [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.app_env == "production":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.app_env == "development" else logging.INFO,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to the given module name."""
    return structlog.stdlib.get_logger(name)
```

#### 步骤 1.2：改造 `backend/src/hypertrade/main.py`

**在 `create_app()` 入口处初始化日志：**

```python
from hypertrade.logging_config import configure_logging, get_logger

def create_app(...):
    configure_logging(settings)
    log = get_logger(__name__)
    log.info("server_starting", host=settings.api_host, port=settings.api_port, env=settings.app_env)
    ...
```

**添加全局 exception_handler（替代每个 endpoint 内联 try/except）：**

```python
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(KeyError)
async def key_error_handler(request: Request, exc: KeyError):
    log = get_logger(__name__)
    log.warning("resource_not_found", path=request.url.path, key=str(exc))
    return JSONResponse(status_code=404, content={"detail": f"Not found: {exc}"})

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    log = get_logger(__name__)
    log.warning("bad_request", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=400, content={"detail": str(exc)})

@app.exception_handler(BitProMcpError)
async def bitpro_error_handler(request: Request, exc: BitProMcpError):
    log = get_logger(__name__)
    log.error("bitpro_upstream_error", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=502, content={"detail": f"BitPro upstream error: {exc}"})
```

**SSE streaming endpoint 加日志：**

```python
@app.post("/api/agent/runs/stream")
def stream_run(payload: AgentRunPayload):
    log = get_logger(__name__)
    log.info("agent_run_requested", prompt_len=len(payload.prompt))
    ...
```

#### 步骤 1.3：改造 `backend/src/hypertrade/agent/kernel.py`

在关键路径加日志（不改变任何业务逻辑）：

```python
from hypertrade.logging_config import get_logger

class AgentKernel:
    def __init__(self, ...):
        self._log = get_logger("hypertrade.agent.kernel")

    def run_chat_with_events(self, prompt, event_sink=None):
        run_id = new_id("run")
        self._log = self._log.bind(run_id=run_id)
        self._log.info("agent_run_started", prompt_len=len(prompt))
        try:
            # ... existing logic ...
            self._log.info("agent_run_completed", status=run.status)
        except Exception as e:
            self._log.error("agent_run_failed", error=str(e), exc_info=True)
            raise

    def _graph_node(self, run_id, node_name: str, ...):
        self._log.debug("graph_node_enter", node=node_name, run_id=run_id)
        # ... existing logic ...
        self._log.debug("graph_node_exit", node=node_name, run_id=run_id)

    def _build_executor(self, ...):
        def execute_tool(tool_name, arguments, call_id):
            start = time.time()
            self._log.info("tool_call_start", tool_name=tool_name, call_id=call_id)

            # governance check
            decision = self._governance.evaluate(...)
            if not decision.allowed:
                self._log.warning("tool_denied", tool_name=tool_name,
                                  reason=decision.reason, call_id=call_id)
                ...

            # execute
            try:
                result = handler(...)
                latency_ms = round((time.time() - start) * 1000)
                self._log.info("tool_call_complete", tool_name=tool_name,
                               call_id=call_id, latency_ms=latency_ms,
                               status="success")
                return result
            except Exception as e:
                latency_ms = round((time.time() - start) * 1000)
                self._log.error("tool_call_failed", tool_name=tool_name,
                                call_id=call_id, latency_ms=latency_ms,
                                error=str(e), exc_info=True)
                ...
```

#### 步骤 1.4：改造 `backend/src/hypertrade/providers/runtime.py`

```python
from hypertrade.logging_config import get_logger

class ProviderRuntime:
    def __init__(self, settings):
        self._log = get_logger("hypertrade.providers.runtime")

    def get_chat_provider(self, ...):
        provider_def = ...
        if not provider_def or not provider_def.enabled:
            self._log.warning("provider_not_available",
                              requested_provider=..., available_providers=...)
            return None
        self._log.info("provider_selected", provider=provider_def.name, model=provider_def.model)
        ...
```

#### 步骤 1.5：改造 `backend/src/hypertrade/providers/chat.py`

在 `OpenAICompatibleChatProvider.chat()` 和 `CodexResponsesChatProvider.chat()` 中加耗时日志。

#### 步骤 1.6：改造 `backend/src/hypertrade/market/client.py`

```python
from hypertrade.logging_config import get_logger

class OkxRestClient:
    def __init__(self, settings):
        self._log = get_logger("hypertrade.market.okx")

    async def fetch_swap_tickers(self):
        start = time.time()
        try:
            result = await self._client.get(...)
            latency_ms = round((time.time() - start) * 1000)
            self._log.debug("okx_rest_call", endpoint="tickers", latency_ms=latency_ms,
                            status=result.status_code)
            return result
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000)
            self._log.error("okx_rest_error", endpoint="tickers", latency_ms=latency_ms,
                            error=str(e))
            raise
```

---

### Phase 2：OpenTelemetry 追踪（Agent 全链路）

#### 步骤 2.1：新建 `backend/src/hypertrade/telemetry.py`

```python
"""OpenTelemetry setup for HyperTrade agent tracing."""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from contextlib import contextmanager


def init_telemetry(service_name: str = "hypertrade") -> None:
    provider = TracerProvider()
    exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


TRACER = trace.get_tracer("hypertrade")


@contextmanager
def traced_span(name: str, **attributes):
    """Context manager for a named OpenTelemetry span."""
    with TRACER.start_as_current_span(name) as span:
        for k, v in attributes.items():
            span.set_attribute(k, str(v))
        yield span
```

#### 步骤 2.2：在 `main.py` 启动时初始化

```python
from hypertrade.telemetry import init_telemetry

def create_app(...):
    configure_logging(settings)
    init_telemetry(settings.app_name)
    ...
```

#### 步骤 2.3：在 `kernel.py` 的 Agent 运行路径嵌入 span

```python
from hypertrade.telemetry import traced_span

def run_chat_with_events(self, prompt, event_sink=None):
    run_id = new_id("run")
    with traced_span("agent_run", run_id=run_id, prompt_len=str(len(prompt))):
        ...

def _graph_node(self, run_id, node_name, ...):
    with traced_span(f"graph.{node_name}", run_id=run_id):
        ...
```

#### 步骤 2.4：在 `planner.py` 的 LLM 调用嵌入 span

```python
def plan_and_execute(self, ...):
    for i in range(MAX_ITERATIONS):
        with traced_span(f"llm.iteration.{i}", model=self._llm.model):
            response = self._llm.chat(messages, tools=tools)
            ...
```

---

### Phase 3：依赖更新

#### 步骤 3.1：编辑 `pyproject.toml`

在 `dependencies` 中添加：

```toml
dependencies = [
    # ... existing ...
    "structlog>=24.4.0",
    "opentelemetry-api>=1.27.0",
    "opentelemetry-sdk>=1.27.0",
    "prometheus-client>=0.21.0",
]
```

#### 步骤 3.2：更新锁文件

```bash
uv lock
```

---

## 验收标准

1. `python -c "from hypertrade.logging_config import get_logger; get_logger('test').info('hello', key='value')"` 输出结构化日志（开发环境带颜色，生产环境 JSON）
2. Agent 运行一次后，stdout 包含完整的 `agent_run_started` → `provider_selected` → `tool_call_start`/`tool_call_complete` × N → `agent_run_completed` 日志链
3. 工具被 governance 拒绝时，日志包含 `tool_denied` + `reason`
4. OpenTelemetry span 输出到 console（开发环境），可通过环境变量切换 OTLP exporter
5. `./scripts/check.sh` 通过

## 面试可讲点

- **结构化日志 vs print**：JSON 输出可直接接入 ELK/Loki，支持按 `run_id`、`tool_name`、`status` 搜索和聚合
- **OpenTelemetry 标准**：业界通用标准，不锁定厂商（Jaeger/Tempo/Datadog 通用）
- **三层可观测性**：Logs（诊断单点问题）、Traces（诊断链路瓶颈）、Metrics（诊断系统趋势）
- **Agent 可审计性**：每次 Agent 运行都有完整 trace，金融系统的合规要求
