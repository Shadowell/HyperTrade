# Sprint Contract: Token Streaming (P1-7 自主性基建)

## Sprint Name

`token-streaming`

## Goal

provider 层支持真 token 流式：planner 最终回答以 `answer_delta` 事件实时流出，
CLI `ht chat` 实时出字（不再转圈等完整报告）。工具调用轮次保持结构化流式解析
（tool_call 增量累积），reasoning 内容不外发。这是 P1 自主性基建的最后一项。

## In Scope

- `OpenAICompatibleChatProvider`：
  - 构造器接受可注入 `client`（测试 DI）。
  - 新方法 `stream_chat(messages, tools, on_delta) -> ChatResponse`：
    `stream=True` + `stream_options.include_usage`；内容增量实时回调
    `on_delta`；tool_call 增量按 index 累积为完整调用；usage 归一化复用；
    reasoning_content 累积但不回调。
- `AgentPlanner.run(..., delta_sink=None)`：provider 支持 `stream_chat` 时走
  流式路径，否则回落 `chat`（Codex Responses 等不受影响）。
- kernel `_run_with_planner`：delta_sink → `answer_delta` 事件进 event_sink
  （SSE/队列自动转发）。
- CLI `render_run_stream`：收到首个 `answer_delta` 即停动画实时出字；
  已流式输出的 run 结束时渲染精简 footer（run id）避免全文重复。

## Out of Scope

- Codex Responses provider 的流式（回落非流式）。
- Textual TUI 的事件流渲染（CLI chat 是主控面）。
- 工具执行过程的增量输出。

## Deliverables

- `providers/chat.py`、`agent/planner.py`、`agent/kernel.py`、`cli.py`。
- `tests/test_provider_streaming.py`：增量顺序、tool_call 跨块累积、usage、
  reasoning 不外发、planner 流式+回落、kernel answer_delta 事件。

## Done Means

- 支持流式的 provider 下，最终回答文本经 delta_sink 实时逐段发出，最终
  ChatResponse 与非流式等价（content/tool_calls/usage）。
- 不支持的 provider 行为逐字节不变。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_provider_streaming.py tests/test_agent_planner.py tests/test_agent_observability.py
./scripts/check.sh
```

## Risks / Notes

- `stream_options.include_usage` 为 OpenAI/DeepSeek 支持项；其他兼容端若拒绝
  会在 planner 回落非流式（捕获后降级）。
- 中间轮次若伴随 content（罕见）也会实时流出——与"实时看到 agent 在写什么"
  的语义一致。

## Handoff

- Next likely step: P2 深度项（RAG 真 embedding / 红队重放 / evals 进 CI）。
