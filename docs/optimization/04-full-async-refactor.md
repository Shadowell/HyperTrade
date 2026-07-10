# 优化计划 4：全链路 async 改造

## 现状诊断

调用链阻塞问题：
1. **OKX REST 客户端是 async 的**（`market/client.py:33-124` 使用 `httpx.AsyncClient`）
2. **Agent kernel 是 sync 的**，通过 `asyncio.run()` 调用 OKX（`kernel.py:1164`, `1175`）
3. **FastAPI endpoint 是 sync 的**，通过 `Thread + Queue` 运行 agent（`main.py:886-916`）
4. **SSE streaming endpoint 在独立线程中跑 kernel**，该线程阻塞在 `asyncio.run()` 上
5. **OKX 客户端每次调用创建新 httpx.AsyncClient**，无连接复用

结果：
- 多 Agent 并发可能触发 `RuntimeError: This event loop is already running`
- 线程因 `asyncio.run()` 阻塞，无法真正并发
- TCP 连接开销大（每次 OKX 调用重新建连接）

## 目标

消除所有 `asyncio.run()` 调用。全链路 async：
- FastAPI async endpoint → AgentKernel async → OKX async → LLM async

## 涉及文件

| 操作 | 文件 |
|------|------|
| 改造 | `backend/src/hypertrade/providers/chat.py` |
| 改造 | `backend/src/hypertrade/providers/deepseek.py` |
| 改造 | `backend/src/hypertrade/providers/codex.py` |
| 改造 | `backend/src/hypertrade/providers/runtime.py` |
| 改造 | `backend/src/hypertrade/agent/planner.py` |
| 改造 | `backend/src/hypertrade/agent/kernel.py` |
| 改造 | `backend/src/hypertrade/market/client.py` |
| 改造 | `backend/src/hypertrade/main.py` |
| 改造 | `tests/test_agent_acceptance.py` |
| 改造 | `tests/test_paper_engine.py` 等适配测试文件 |

---

## 改造层自底向上

### Layer 1：ChatProvider Protocol 加 async

**文件**：`backend/src/hypertrade/providers/chat.py`

```python
from typing import Protocol

class ChatProvider(Protocol):
    name: str
    model: str

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse: ...

    async def chat_async(self, messages: list[dict],
                         tools: list[dict] | None = None) -> ChatResponse: ...
```

### Layer 2：各 Provider 实现 chat_async

**DeepSeekClient**（`providers/deepseek.py`）：

```python
from openai import AsyncOpenAI

class DeepSeekClient:
    def __init__(self, ...):
        self._sync_client = OpenAI(base_url=base_url, api_key=api_key)
        self._async_client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def chat_async(self, messages, tools=None):
        response = await self._async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            temperature=0.1,
        )
        return self._parse_response(response)
```

**OpenAICompatibleChatProvider**（`providers/runtime.py` 中的内部类）：

同上，切换为 `AsyncOpenAI`。

**CodexResponsesChatProvider**（`providers/codex.py`）：

Codex 无官方 async SDK。实现方式：`asyncio.to_thread(self.chat, messages, tools)`（仅在 provider 层用，不在 kernel 层用 `asyncio.run`）。

```python
import asyncio

class CodexResponsesChatProvider:
    async def chat_async(self, messages, tools=None):
        return await asyncio.to_thread(self.chat, messages, tools)
```

**ProviderRuntime**（`providers/runtime.py`）：

`get_chat_provider()` 保持不变，返回的 `ChatProvider` 实例同时有 `chat()` 和 `chat_async()` 方法。

### Layer 3：AgentPlanner async

**文件**：`backend/src/hypertrade/agent/planner.py`

```python
class AgentPlanner:
    async def plan_and_execute_async(
        self, intent: str, executor: ToolExecutor
    ) -> PlannerResult:
        messages = [{"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": intent}]
        tool_records: list[dict] = []

        for iteration in range(MAX_ITERATIONS):
            response = await self._llm.chat_async(messages, tools=TOOL_SCHEMAS)
            tool_calls = response.tool_calls or []

            if not tool_calls:
                break

            for tc in tool_calls:
                result = await executor(tc.name, tc.arguments, tc.call_id)
                tool_records.append({...})
                messages.append({"role": "tool", "content": json.dumps(result), ...})

        final = messages[-1]["content"]
        return PlannerResult(message=final, tool_record_refs=tool_records)
```

关键变化：
- `self._llm.chat(messages, tools=tools)` → `await self._llm.chat_async(messages, tools=tools)`
- `executor(tool_name, arguments, call_id)` → `await executor(tool_name, arguments, call_id)`

### Layer 4：AgentKernel async

**文件**：`backend/src/hypertrade/agent/kernel.py`

```python
class AgentKernel:
    async def run_chat(self, prompt: str) -> dict:
        """完整运行（非流式）。"""
        run = self._create_run(prompt)
        try:
            planner_result = await self._run_with_planner(run.id, prompt, self._build_executor(...))
            self._complete_run(run.id, planner_result)
            return self._load_run(run.id)
        except Exception as e:
            self._fail_run(run.id, str(e))
            raise

    async def run_chat_with_events(self, prompt: str, event_sink) -> None:
        """SSE 流式运行。"""
        run = self._create_run(prompt)
        event_sink({"event": "run_started", "data": {"run_id": run.id}})

        try:
            executor = self._build_executor(run.id, event_sink)
            planner_result = await self._run_with_planner(run.id, prompt, executor)
            self._complete_run(run.id, planner_result)
            event_sink({"event": "final", "data": self._load_run(run.id)})
            event_sink(None)  # sentinel
        except Exception as e:
            self._fail_run(run.id, str(e))
            event_sink({"event": "error", "data": {"error": str(e)}})
            event_sink(None)

    async def _run_with_planner(self, run_id, prompt, executor):
        return await self._planner.plan_and_execute_async(prompt, executor)

    # _build_executor 返回的闭包必须也是 async
    def _build_executor(self, run_id, event_sink):
        async def execute_tool(tool_name, arguments, call_id):
            handler = self._tool_handlers.get(tool_name)
            if handler is None:
                return self._tool_error_payload(call_id, f"Unknown: {tool_name}")

            decision = self._governance.evaluate(...)
            if not decision.allowed:
                return self._governance_denial_payload(...)

            try:
                result = await handler.execute(arguments, call_id)  # async handler
                self._emit_tool_event(event_sink, run_id, tool_name, ...)
                return result.payload
            except Exception as e:
                return self._tool_error_payload(call_id, str(e))

        return execute_tool
```

对二级方法的改造：
- `_fetch_market_candles()` — 改为 `async`，直接 `await client.fetch_candles(...)`，删除 `asyncio.run()`
- `_refresh_market_snapshot()` — 同上
- `_graph_node()` — 改为 `async`（当前无 IO，但保持接口一致）

### Layer 5：OKX 客户端连接复用

**文件**：`backend/src/hypertrade/market/client.py`

```python
class OkxRestClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                base_url=self._settings.okx_rest_url,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_swap_tickers(self) -> list[OkxTicker]:
        client = await self._ensure_client()
        resp = await client.get("/api/v5/market/tickers", params={"instType": "SWAP"})
        resp.raise_for_status()
        data = resp.json()
        return [OkxTicker.from_api(item) for item in data.get("data", [])]

    # fetch_candles, fetch_funding_rate, fetch_open_interest 同样模式
```

### Layer 6：FastAPI endpoint async

**文件**：`backend/src/hypertrade/main.py`

```python
@app.post("/api/agent/runs")
async def run_agent(payload: AgentRunPayload, admin: AdminUser):
    """同步运行 Agent，等待完成后返回。"""
    kernel = AgentKernel(...)
    run = await kernel.run_chat(payload.prompt)
    return RunResponse(**run)


@app.post("/api/agent/runs/stream")
async def stream_run(payload: AgentRunPayload, admin: AdminUser):
    """SSE 流式运行，实时推送事件。"""
    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        kernel = AgentKernel(...)
        task = asyncio.create_task(
            kernel.run_chat_with_events(payload.prompt, queue.put)
        )
        while True:
            event = await queue.get()
            if event is None:
                break
            yield _format_sse(event)
        await task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

关键变化：
- `@app.post(...)` → endpoint 函数 `async def`
- `threading.Thread` + `Queue` → `asyncio.create_task` + `asyncio.Queue`
- `global_queue` 变量 → 函数内 `asyncio.Queue()`，无需全局变量

### Layer 7：测试适配

**文件**：`tests/test_agent_acceptance.py`

`ReplayDeepSeekClient` 和 `ReplayChatProvider` 需要添加 `chat_async()`：

```python
class ReplayDeepSeekClient:
    def chat(self, messages, tools=None):
        self._captured_messages.append(messages)
        return self._consume_next_response()

    async def chat_async(self, messages, tools=None):
        # 复用 sync 实现（replay 无真实 IO）
        return self.chat(messages, tools)
```

所有调用 `kernel.run_chat()` 或 `kernel.run_chat_with_events()` 的测试需要加 `await`：

```python
# 之前
run = kernel.run_chat("market summary")

# 之后
run = await kernel.run_chat("market summary")
```

需要在 async 函数中执行的测试用 `@pytest.mark.asyncio` 或直接在 `async def test_*` 中写。

---

## 实施步骤

1. **Layer 1-2**：在 `ChatProvider` Protocol 加 `chat_async()`，各 Provider 实现
2. **Layer 5**：OKX 客户端连接复用（独立改造，不影响上层）
3. **Layer 3**：`AgentPlanner` 加 `plan_and_execute_async()`
4. **Layer 4**：`AgentKernel` 全链路 async
   - `_build_executor()` 的返回闭包改为 `async`
   - 删除 `asyncio.run()` 调用
   - `_graph_node()` 改为 `async`
5. **Layer 6**：`main.py` endpoint 改为 `async def`，SSE 改用 `asyncio.Queue`
6. **Layer 7**：全部测试适配

---

## 验收标准

1. `rg "asyncio.run\(" backend/` 返回零结果
2. 两个 Agent 并发运行不报 `RuntimeError: This event loop is already running`
3. SSE streaming 在 Agent 运行期间不阻塞其他 HTTP 请求
4. `httpx.AsyncClient` 实例在 `OkxRestClient` 生命周期内复用（只创建一次）
5. 所有 254 个测试通过（适配 async 后）
6. `./scripts/check.sh` 通过

## 面试可讲点

- **async/await 本质**：协程是协作式调度，不是多线程；`asyncio.run()` 创建新事件循环的开销
- **FastAPI async endpoint**：在同一个 event loop 中调度所有请求，不存在 GIL 问题（IO bound）
- **asyncio.Queue vs threading.Queue**：天然适合 async producer/consumer，不用锁
- **连接池复用**：`httpx.AsyncClient` 的 keep-alive 连接池，减少 TCP 握手开销（每请求省 100-200ms）
- **为什么改造**：当前方案在单线程单 Agent 时可行，但面试官会追问"10 个 Agent 同时运行呢？"
- **asyncio.create_task vs Thread**：线程有切换开销和 GIL，协程切换开销接近零
