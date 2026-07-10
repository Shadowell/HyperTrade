# 02 Agent Harness / Agent Harness

## English

`AgentKernel` is the Sprint 01 runtime boundary. It is intentionally explicit: it creates a run, calls tools in order, records trace events, writes memory, and stores Markdown plus JSON reports.

The implementation follows LangGraph architecture ideas: durable run state, tool execution nodes, human approval gates for dangerous actions, and observable transitions. Sprint 01 keeps the graph compact so the flow is easy to inspect before adding autonomous trading loops.

Sprint 76 adds a trace-safe Flight Recorder projection. Each planner iteration
records provider/model, latency, tool-call count, and provider-reported Token
usage as `graph.model_call`; tool and Memory events keep their execution order.
The projection intentionally excludes prompts, credentials, and private model
reasoning text. DB Trace remains the audit record while the Flight Recorder is
an operator-facing summary view.

## 中文

`AgentKernel` 是 Sprint 01 的运行时边界。它显式创建 run、顺序调用工具、记录 trace、写入 memory，并保存 Markdown 和 JSON 报告。

实现遵循 LangGraph 的架构思路：持久化运行状态、工具执行节点、危险动作人工审批、可观测状态转移。Sprint 01 先保持图很小，便于排障和审计，再扩展自动交易。

Sprint 76 增加安全的 Flight Recorder 投影：每轮 Planner 调用把
Provider/Model、延迟、工具调用数和 Provider 返回的 Token usage 记录为
`graph.model_call`，工具与 Memory 事件保持真实执行顺序。投影不保存 prompt、
凭据或模型私有推理文本；数据库 Trace 仍是审计记录，Flight Recorder 只是
面向操作员的摘要视图。
