# 12 Agent Graph Runtime

## Purpose

HyperTrade now models each Agent run as a traceable graph-style runtime while preserving the `AgentKernel.run_chat()` interface used by API and CLI.

## Graph Nodes

| Node | Responsibility | Trace name |
| --- | --- | --- |
| `intent_classify` | Classify the user prompt into market, strategy, order, or general intent. | `graph.intent_classify` |
| `plan_tools` | Select planner path: configured chat provider or deterministic fallback. | `graph.plan_tools` |
| `approval_check` | Decide whether a tool requires approval. Live order intent remains gated. | `graph.approval_check` |
| `execute_tool` | Execute the selected tool and emit progress. | `graph.execute_tool` |
| `reflect` | Summarize tool use and execution outcome. | `graph.reflect` |
| `final_report` | Produce final Markdown/JSON report. | `graph.final_report` |

## State

`agent_runs.run_state_json` stores:

- `graph`: ordered node events with input/output
- `current_node`: latest completed graph node
- `final_answer`: final Markdown report

Business tool calls remain stored in `trace_events` alongside graph node events. Consumers should filter `tool_name.startswith("graph.")` when they only need business tools.

## Planner Paths

- With a configured provider: `ProviderRuntime.get_chat_provider()` returns a `ChatProvider` and `AgentPlanner` uses function calling.
- Without a configured provider: deterministic fallback runs market summary, RAG search, and memory write.

## UI/CLI

- Streaming API emits `graph_node` events.
- CLI displays progress events and final report.
- `/harness` shows current stage and trace stream.

