# Sprint Contract: Industrial Agent Runtime Hardening

## Sprint Name

`industrial-agent-runtime-hardening`

## Goal

按工业级 Agent 标准修复 Agent Runtime 的四类结构性缺陷：工具面多源漂移、执行层无硬超时、
同步栈阻塞事件循环、Memory 只写不读。交付后，工具 schema 只有单一事实来源，任何工具挂死
都能按时限返回结构化 payload，API 事件循环不被长请求卡住，记忆能确定性地进入 planner 上下文。

## In Scope

- 工具单一事实来源：planner-facing OpenAI schemas 从 `tools/registry.py` 派生；
  并行只读白名单从 registry policy scope 派生（不再手工维护三份清单）。
- 真超时：`AgentKernel._dispatch_tool` 经共享线程池以 `timeout_class`
  （quick/standard/long → 5s/30s/120s）为硬 wall-clock deadline。
- API 卸载：`POST /api/agent/runs` 的同步 kernel 执行移入 worker 线程。
- Harness telemetry 贯通：healer/dispatcher 每 run 实例化一次，
  聚合延迟/错误/重试指标写入 run observability 的 `tools.telemetry`。
- Water cooler 递归截断嵌套数组/字符串。
- Memory recall 闭环：`memory_search` schema 支持 query/kind/tag/limit；
  `memory_write` 支持 tags/importance/confidence（服务端 clamp）；
  高重要性记忆与 governed assertions 注入 planner system prompt
  （`AGENT_MEMORY_PROMPT_INJECTION`，默认开）。
- RAG rescan 门控：目录签名（path/mtime_ns/size）未变时跳过全盘重读。

## Out of Scope

- Provider 层全异步化（AsyncOpenAI 迁移）；本轮用 to_thread 卸载达成同等隔离。
- Memory/RAG 向量检索升级（pgvector、真 embedding provider）。
- 幂等锁的分布式化（跨进程去重仍由下游 DB unique key 承担）。
- System prompt 瘦身与 prefix-cache 对齐。

## Deliverables

- `backend/src/hypertrade/tools/registry.py`：RUNTIME_TOOL_SCHEMAS + 派生函数。
- `backend/src/hypertrade/agent/harness_v2.py`：派生只读集合 + 递归 water cooler。
- `backend/src/hypertrade/agent/planner.py`：每 run 单一 harness、telemetry 回传、
  删除三个无生产引用的 executor 类。
- `backend/src/hypertrade/agent/kernel.py`：`_dispatch_tool` + `_invoke_tool_with_timeout`、
  memory prompt 注入 seam、telemetry 入 observability。
- `backend/src/hypertrade/main.py`：create_run 的 `asyncio.to_thread` 卸载。
- `backend/src/hypertrade/memory/service.py`：SQL 下推过滤 + usage 审计修正 +
  `prompt_context()`。
- `backend/src/hypertrade/rag/service.py`：签名门控 rescan。
- 测试：registry 漂移守卫、water cooler 嵌套截断、memory 下推/注入开关、
  RAG 门控、planner telemetry 聚合。

## Done Means

- 新增运行时工具必须且只需改 registry 一处即可同时出现在 planner schema 与治理面。
- 任一工具执行超过其 timeout_class 上限时，run 收到
  `execution_status=timeout` 的结构化 payload 并继续规划。
- 一个长时间 agent run 进行期间，`GET /api/health` 与 SSE 流不受阻塞。
- 空 query 之外的 memory_search 能按 query/kind/tag 过滤；高重要性记忆无需模型
  主动搜索即出现在 system prompt。
- rag_search 在知识库未变化时不再触发全文件读取。

## Verification

```bash
uv run pytest -q tests/test_tool_registry.py tests/test_agent_harness_v2.py \
  tests/test_agent_planner.py tests/test_rag_memory.py tests/test_agent_observability.py
./scripts/check.sh
```

Manual or QA checks:

- 观测 `tools.telemetry` 出现在 `/api/agent/runs/{id}/observability` 投影中。
- 关闭 `AGENT_MEMORY_PROMPT_INJECTION` 后 system prompt 不再包含 `[memory` 标记。

## Risks / Notes

- 超时后工作线程可能继续等待底层 IO 直到自然结束，其结果被丢弃；
  这是同步栈下的已知边界，Provider 全异步化后才可真正取消。
- `bitpro_paper_monitor_snapshot`（research_write scope）从并行只读集合中退出，
  混批时改为顺序执行——语义更保守。
- SQLite `:memory:` 测试依赖 StaticPool 共享连接；超时池与并行分发共用该假设。

## Handoff

- Next likely step: Provider 全异步化 + 真 embedding 检索层（pgvector）。
