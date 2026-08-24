# Sprint Contract: Team LLM Worker (P0-2 自主性支柱②)

## Sprint Name

`team-llm-worker`

## Goal

把 supervisor 的 `AssignmentWorker` 从确定性罐头桩升级为**真 LLM worker**：每个
assignment（research_lead/market_analyst/evidence_analyst/critic）由 LLM 基于
Mission Context Pack 的证据内容推理产出结构化 Handoff（claims/unknowns/summary），
使 bull/bear/critic 式的多角色协作第一次产生真实的多轮对抗语义。信任边界保持：
worker 无分发权、无写能力、handoff 必须引用其 Context Pack、输出哈希绑定、
禁止隐藏推理文本，失败回落确定性桩并在 claims 中显式标注降级来源。

## In Scope

- `llm_assignment_worker(provider, pack_loader, roles)`：单次 LLM + 一次修复回合 +
  确定性回落（回落 handoff 带 `mode=deterministic_fallback` 审计标记）。
- Context Pack 内容注入（decisions[].rendered_content，总预算有界）。
- 输出校验：JSON-only、summary/claims/unknowns 边界、HandoffV1 哈希与禁词合同、
  必须引用所分配的 Context Pack。
- `build_team_worker(settings, ...)` 工厂 + 新 flag `AGENT_TEAM_LLM_WORKER_ENABLED`
  （默认开，flag 关/无 provider 时行为与现状一致）。
- `POST /api/agent/missions/{id}/team/run` 接线。

## Out of Scope

- Worker 内执行 capability（工具执行仍属 mission plan steps；worker 只做证据推理）。
- BoundedSupervisor 状态机/预算预留/冲突合并逻辑不动。
- 角色目录扩展。

## Deliverables

- `runtime/adapters/supervisor.py`：llm_assignment_worker + build_team_worker。
- `config.py`：新 flag。
- `main.py`：run_agent_team 接线（pack 内容映射传入 worker）。
- `tests/test_team_llm_worker.py`：黄金路径、修复回合、双败回落带审计标记、
  provider 异常、空 pack 诚实失败、禁词合同、工厂分支、supervisor 端到端对抗合并。

## Done Means

- flag 开 + provider 可用时，team run 的 handoffs 来自 LLM 推理且可审计区分来源。
- flag 关或 LLM 失败时，行为与现状完全一致（确定性桩）。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_team_llm_worker.py tests/test_agent_supervision*.py
./scripts/check.sh
```

## Risks / Notes

- LLM 延迟进入 team run（受 assignment.timeout_seconds ≤300s 与 supervisor
  fail_after 约束）。
- Worker 不执行工具，claims 的证据边界 = Context Pack 内容；越界断言靠 critic
  角色与冲突合并不兜底为真。

## Handoff

- Next likely step: P0-3 ARC 搜索智能接线（UCB1/QD/技能库进生产循环）。
