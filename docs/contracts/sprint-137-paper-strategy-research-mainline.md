# Sprint Contract: Paper Strategy Research Mainline Tool Surface

## Sprint Name

`paper-strategy-research-mainline`

## Goal

把「Agent 驱动的模拟盘策略研究」定为项目主线：补齐 Agent 工具面上缺失的两个关键环节——
按 operator 锁定标准做验证门禁自检、对已过检证据发起模拟盘晋升请求——使 Agent 能在
受治理边界内完成 `查证据 → 生成/创建策略 → BitPro 回测 → 门禁自检 → 请求晋升（人工审批）
→ 模拟盘观察` 的完整闭环。服务层（orchestrator / PaperPromotionService）已存在，
本轮只接工具面，不新造执行语义。

## In Scope

- 新增只读工具 `research.validation_gate`：以 mandate 的 `validation_json`
  （operator 锁定）为唯一标准来源，服务端跑 `ValidationGate.evaluate`；
  模型只能提交结果行，不能提交阈值。
- 新增写入工具 `paper.promotion_request`：包装
  `PaperPromotionService.request(evidence_id, reason)`；仅接受
  `evidence_recorded` 且门禁全过的证据，实际 configure/start 仍由 operator 审批触发。
- registry 单一事实来源同步：dot name、runtime schema、policy、idempotency 注入、
  只读派生集合。
- `_SYSTEM_PROMPT` 增加主线路由规则（先库检索、后回测、门禁自检、证据晋升、
  不虚报模拟盘已启动）。
- 校准 `research_job_report.outcome.paper_promotion` 的过期标签。

## Out of Scope

- 自动批准任何 paper_configure/paper_start（保持 Sprint 83 边界：agent 侧 blocked）。
- ARC 引擎改动；robustness 矩阵扩展。
- 真 BitPro 外部调用验证（用 fixture adapter 与单元夹具；真身 smoke 由 operator 执行）。

## Deliverables

- `tools/registry.py`：两个新工具定义、schema、策略与幂等注入。
- `agent/kernel.py`：两个 executor 分支 + 主线 prompt 规则。
- `research/service.py`：outcome 标签校准。
- 测试：registry 漂移/幂等、门禁分支（过/不过/mandate 缺失）、晋升请求分支
  （过检证据成功 / 未过检拒绝 / 幂等重复返回同一记录）。

## Done Means

- Agent 可对一个 BitPro 回测结果行集请求门禁判定，阈值不可被模型影响。
- Agent 可对全过检证据创建 pending_paper_approval 记录；operator 不批准则
  BitPro 模拟盘零副作用。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_tool_registry.py tests/test_agent_kernel_tools.py \
  tests/test_research_orchestrator.py
./scripts/check.sh
```

Manual or QA checks:

- governance 对 `bitpro_paper_start` 仍返回 blocked（既有测试继续通过）。

## Risks / Notes

- 门禁自检的 results 行来自模型上下文（advisory）；权威门禁仍在 orchestrator
  落证据时服务端执行，两者标准同源（mandate），不存在双标。
- 晋升请求幂等依赖 evidence_id 唯一约束，重复请求返回既有记录而非报错。

## Handoff

- Next likely step: operator 审批后的 paper observe 工具化（已有读面）+
  真身 BitPro smoke。
