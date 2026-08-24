# Sprint Contract: ARC Search Intelligence Wiring (P0-3 自主性支柱③)

## Sprint Name

`arc-search-intelligence-wiring`

## Goal

把 ARC 内核里"存在但不在生产路径"的搜索智能全部接线：UCB1 选择驱动代际变异
父本挑选、MAP-Elites 精英反哺变异素材、Voyager 技能库事件持久化并注入 provider
假设通道、默认搜索预算提升到能支撑搜索叙事的量级。ARC 从"模板目录广度搜索"
升级为"被搜索策略驱动的进化内核"。

## In Scope

- UCB1 引导的变异父本选择：按 UCB1 分数排序当前代 rollout，预算紧张时只变异
  top 片段（探索不足的节点因 visits 少获得探索加成）。
- QD 精英反哺：每代咨询 `qd_grid.get_elites()`，精英尝试加入变异父本集
  （去重、有界），并落 `qd_elites_consulted` 审计事件。
- 技能库事件持久化：`skill_registered` 事件落库，循环重启时从 projection 重建；
  `format_skills_for_prompt` 增加有界输出并注入 provider 假设通道 payload。
- 默认 `max_candidates` 5 → 10（合同无上界，测试均显式传参）。

## Out of Scope

- Regime 归因真实测量化（walk-forward 喂归因）与红队重放攻击升级——留下一合同。
- MCTS 树/网格跨进程持久化（本轮以事件审计 + 精英反哺实现"记忆"语义的第一层）。
- 搜索空间扩展（新策略家族）。

## Deliverables

- `arc/router.py`：UCB1 父本选择、精英反哺、技能库重建/注册事件、skills 注入。
- `arc/skills.py`：有界 prompt 格式化。
- `arc/provider_hypothesis.py`：`propose(skills_context=...)`。
- `arc/contracts.py`：预算默认值。
- 测试：UCB1 选择在预算压力下聚焦、精英反哺生效、技能跨循环持久化并进入
  provider payload、默认预算。

## Done Means

- 预算紧张时变异花费集中在高 UCB1 节点（测试可观测选择顺序）。
- 精英节点成为下一带变异父本且审计事件可查。
- 上一循环注册的技能在本循环的 provider prompt 中可见。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_arc_mcts.py tests/test_arc_skills.py tests/test_arc_acceptance.py tests/test_arc_kernel.py
./scripts/check.sh
```

## Risks / Notes

- 默认预算翻倍会提高单 mission 成本上限；mission 本身有 operator 预算审批。
- UCB1 选择只重排/裁剪当前代父本，不改变代际语义（每代仍先全量评估）。

## Handoff

- Next likely step: Regime 归因真实测量化 + 红队重放攻击（P2 深度项）。
