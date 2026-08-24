# Sprint Contract: Mission LLM Planner (P0-1 自主性支柱①)

## Sprint Name

`mission-llm-planner`

## Goal

把 Mission runtime 的规划层从"LLM 只抽取意图符号 + 关键词路由决定计划"升级为
**LLM 直接提议步骤 DAG**（选哪些能力、什么顺序、什么参数），同时保持既有安全属性：
能力只能来自已审核目录、参数必须过 input_schema、金融实体必须逐字来自用户目标、
任何验证失败回落确定性 planner。这是"从结构化流水线跨到治理型自主 Agent"的单点最大杠杆。

## In Scope

- `LlmPlanV2Planner`：单次 LLM 提议 + 一次修复回合 + 确定性回落。
- 验证管道：capability 白名单（read/approval=none/side_effect=none 信封）、
  jsonschema 参数校验、市场实体逐字校验（复用 `_validated_provider_market_instrument`）、
  PlanV2 DAG 校验、步数上限（mission budget）。
- 工厂 `build_mission_planner(settings, provider)`：flag 关/无 provider 时行为与现状一致。
- 接线 main.py / worker.py / cli.py 三处构造点。
- 新 flag `MISSION_LLM_PLANNER_ENABLED`（默认开，失败路径零新风险）。

## Out of Scope

- GovernedToolExecutor / CatalogCapabilityPolicy 不动（分发时仍二次校验）。
- Sub-agent 派生（P0-2）、上下文 compaction（P1）。
- 写能力不进入 LLM 可选信封。

## Deliverables

- `runtime/adapters/research_planner.py`：LlmPlanV2Planner + 工厂。
- `config.py`：新 flag。
- 三处构造点接线。
- `tests/test_mission_llm_planner.py`：黄金路径、越权能力拒绝、schema 违例修复后回落、
  实体逐字规则、步数上限、provider 异常回落、replan、工厂分支。

## Done Means

- LLM 返回合法 DAG 时，mission 按其计划执行；非法时回落计划与现状完全一致。
- 既有 `test_research_mission_planner.py` 全部通过（ProviderBackedResearchPlanner 语义不变）。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_mission_llm_planner.py tests/test_research_mission_planner.py
./scripts/check.sh
```

## Risks / Notes

- LLM 延迟进入 mission 规划路径（≤2 次调用）；mission 本身受 canary 百分比门控。
- 模型无法发明新能力或写操作：信封过滤在构造时完成，分发时 CatalogCapabilityPolicy 再拦一次。

## Handoff

- Next likely step: P0-2 sub-agent 派生（AssignmentWorker 接真 LLM worker）。
