# User-Directed Contract — ARC 真身闭环与 Provider 假设层

> 状态：Delivered（2026-08-23 四个 Slice 全部交付，生产 canary 完成；待产品所有者验收）。
>
> 激活原因：产品所有者于 2026-08-19 确认第一档目标——把 ARC 研究闭环在**真实 BitPro + 真实
> 行情 + 真实 Provider** 上第一次走通正路，并把 LLM 以"假设提出者"身份接回蓝队。
>
> 优先级：当前最高。Sprint 132–134 的实盘路线保持未激活。
>
> 前置关系：本合同是
> [User-Directed M0 合同](user-directed-autonomous-strategy-research-loop-m0.md) 的延续，填充其两个
> 未达成项：Done Means #2（真实 Provider 产生候选）与 #14（生产 Canary 的正路真身验证）。M0 的
> Safety Boundaries 1–15 全部继续有效，本合同不再重复。
>
> 交付记录（2026-08-23）：Slice 1 `fb16c80`；Slice 3 真身探针 run `03baf9b7`
> （validate/create/backtest 首次真身全链，strategy_id=445、backtest_id=450）；Slice 2
> `02a55ef`（Provider 通道，flag 默认关闭）；Slice 4 生产 canary mission
> `arc_8b18d07c4d66` 诚实终态 needs_operator(no_validated_candidate)，6/6 候选含
> 1 个 Provider 假设（codex:gpt-5.4），零 fixture 零编造 ref。

## Goal

今天 ARC 的闭环是"真的但封闭的"：闭环成立、门禁诚实、失败如实报告，但候选只来自 6 个确定性模板
族（`research/codegen.py` 的 `FAMILIES`），整个 `arc/` 包没有一处 LLM 调用；Gate 2 端到端只在
BitPro 契约替身上验证过；证据窗口的真实来源是替代交易所而非 OKX。本合同不新增 Gate，不做 Live，
只回答一个问题：

> 一个自然语言目标，在全部真实组件上，能不能走到 `paper_observing`——或者诚实地停在
> `needs_operator`，且两种终态的每一句陈述都有真实引用背书。

## User-Visible Outcome

操作员提交：

```text
POST /api/v1/arc/missions
{
  "objective": "研究一个适应BTC高波动的趋势策略，过检后自动上线模拟盘",
  "symbol": "BTC-USDT-SWAP",
  "max_candidates": 6,
  "paper_preauth_approved": true
}
```

得到的 mission 中：

1. 至少一个候选的 provenance 是 `provider`（模型、版本、请求 hash 可见），至少一个候选的
   provenance 是 `deterministic_family`；两类候选走同一套确定性门禁。
2. 每个通过本地预筛的候选都有真实 BitPro `strategy_validate_code` / `strategy_create` /
   `backtest_start_job` / result 引用；没有任何 `bitpro_paper_strat_*` 编造 id。
3. 终态是 `paper_observing`（真实 BitPro paper `instance_id`）或 `needs_operator` / `failed`，
   且证据视图里不存在 fixture、合成或替身来源。

## In Scope

- 证据窗口的来源合同：`evidence/preflight` 与每个 attempt 的证据记录必须携带
  `source_origin`（`okx_swap` / `alternative_exchange` / `archive_unknown`）、`as_of`、
  覆盖根数与来源 hash。默认要求 `okx_swap`；部署网络不可达 OKX 时，允许操作员显式确认
  替代来源，mission 投影必须把替代来源标为显式事实而不是静默降级。
- Provider 假设通道：`BlueTeamQuant.propose_initial_strategy` /
  `propose_diverse_frontier` 增加 `provider_hypothesis` 来源。Provider 经 `ChatProvider`
  结构化输出（目标解释 → 市场现象 → 可证伪规则假设 → `research_strategy_spec.v1` 形状的
  参数化 spec），spec 经现有 `research/codegen.py` 确定性编译；Provider 也可直接提交白名单
  AST 内的新规则体，编译前过同一套 `static_code_rejections()` 门禁，产物做规范化后取
  代码指纹。Provider 不可用时循环照常走完确定性族路径，mission 投影记
  `provider_unavailable`。
- 真实性绑定：Provider 候选携带 `provider` / `model` / `request_hash` provenance，落
  `arc_missions` 投影与证据视图；同一 spec 重复编译必须字节级一致（现有指纹幂等不变），
  因此 Provider 候选的可复现单位是 *spec*，不是自由文本。
- 真身接线：ARC 生产路径上的 BitPro 调用（validate / create / backtest / paper
  configure+start）移除契约替身依赖；`self_test.py` 的真实握手路径成为 canary 的必测项。
  任何 `effect_unknown` 先对账，禁止盲发。
- 口径标注固化：本地回放（`backtest/candidate.py`）在投影与证据视图中恒标注为
  `prefilter_only`；`success_criteria` 裁决只绑定真实 BitPro result ref。用测试钉住这两条。
- 生产真身 canary：一次真实 mission（真实 Provider + 真实 BitPro + 真实证据窗口），
  终态按 M0 合同 Canopy 规则诚实落定；结果与全部外部引用记入 `docs/progress.md`。

## Out of Scope

- Live、Testnet、订单、资金划转、LiveTradingMandate 的任何实现（Sprint 132–134 保持未激活）。
- 本地回放与 BitPro 回测的**统一**口径（只钉标注，不合并引擎）——列入 Handoff。
- Champion/Challenger 自动比较接入 ARC 观察窗；Research Trigger 接入 ARC；StockPro。
- 多标的、多周期、组合搜索；第二个 Provider 或 Provider 自动评分。
- 删除或重构 `agent/kernel.py`、`research/graph.py`、`runtime/` 等旧路径（单独立项）。
- 前端改版；README "SOTA" 命名的修订（单独立项）。

## Safety Boundaries

继承 M0 合同 Safety Boundaries 1–15，另加：

1. Provider 输出在任何情况下不得改变 `ARCGoalV1` 的 `success_criteria`、预算上限、
   `live_allowed`、Paper 预授权或状态迁移集；结构化校验失败 → 该候选作废并记
   `provider_spec_invalid`，不进入 codegen。
2. Provider 候选与确定性族候选共用同一个 `ARCSuccessCriteriaV1` 裁决，不允许为
   Provider 候选放宽阈值。
3. Provider 候选的 AST 白名单外的构造（含 `getattr`、`eval`、网络调用、非内联 import）
   在编译前被 `static_code_rejections()` 拒绝；被拒原因入证据视图。
4. 替代数据源只能在操作员显式确认后使用；`source_origin != okx_swap` 的 mission
   证据视图必须把这一事实渲染出来，进度徽章不得省略。
5. 替身（契约替身 / fixture / 合成指标）不得出现在生产 canary 的任何外部引用中；
   测试替身只允许存在于测试进程内。

## Implementation Slices

每个 Slice 是独立已验证提交；未达 Done Means 不进入下一 Slice。

### Slice 1 — 证据来源合同

- `ARCEvidenceWindow` / preflight 投影增加 `source_origin` / `as_of` / `bars_available` /
  `source_hash`；`alternative_exchange` 需要 mission 创建参数中的显式
  `alternative_source_confirmed: true`，否则 `evidence_window_unavailable`。
- 证据视图与 pipeline 徽章渲染替代来源事实。
- Done：preflight 与证据视图的来源字段有 schema、认证与缺失路径测试；未确认的替代来源
  走 `needs_operator(evidence_window_unavailable)`，与现状一致但来源可见。

### Slice 2 — Provider 假设通道

- `ChatProvider` 结构化调用端口（spec 形状输出，重试 1 次后记 `provider_spec_invalid` /
  `provider_unavailable`，不阻塞确定性路径）。
- `BlueTeamQuant` 双来源：`deterministic_family`（现有 `propose_diverse_frontier`）+
  `provider_hypothesis`；两者汇入同一 frontier 与 MCTS budget。
- codegen 消费 Provider spec（族 key + 参数 bounds + 方向 + 风控叠加），白名单 AST 规则体
  走规范化 + 指纹。
- provenance 落投影；`provider_unavailable` 与 `provider_spec_invalid` 是显式终态事实。
- Done：Fake Provider 黄金测试中一条 mission 同时含两类 provenance 的候选并各自走到
  门禁；同 spec 重复编译字节一致；Provider 输出越界（改预算/阈值/加禁用构造）全部被拒且
  有测试钉住。

### Slice 3 — 真实 BitPro 正路

- 移除生产路径对契约替身的依赖；validate → create → backtest job → result →
  `success_criteria` 裁决 → paper configure → start（`instance_id` 来自 configure 返回）
  全链路真实。
- `effect_unknown` / 超时 / 重复请求路径回归（M0 Done Means #9/#10 在真实 adapter 上重验）。
- Done：集成测试用真实 adapter 接口形状覆盖正路与 3 条故障路径；无编造 id（复用
  `test_arc_hollow_claims.py` 的断言面并把替身断言扩展为本 Slice 的"无替身"清单）。

### Slice 4 — 生产真身 canary 与收口

- 部署后跑一次真实 mission（真实 Provider + 真实 BitPro + 按 Slice 1 规则确认的来源）。
- 终态如实记录：`paper_observing` 附真实 `instance_id` 与观察快照，或
  `needs_operator` / `failed` 附完整真实证据与原因码。
- `docs/progress.md` 记录 canary 全部外部引用与诚实结论；`./scripts/check.sh` 通过。

## Done Means

1. 一条真实 mission 的候选 provenance 同时包含 `provider` 与 `deterministic_family`，
   且 Provider 候选带 model / request_hash。
2. 该 mission 每个过预筛候选都有真实 BitPro validate / create / backtest / result 引用。
3. 候选过检且 Paper 预授权有效时，mission 到达 `paper_observing` 且
   `paper_instance_id` 来自真实 configure 返回；无候选过检时到达
   `needs_operator(no_validated_candidate)` 或等价原因码，两种终态均不出现 fixture /
   合成 / 编造 ref。
4. Provider 不可用或 spec 非法时，mission 以显式原因码继续或终止，确定性路径不受影响。
5. `success_criteria` 裁决在测试层面只接受真实 BitPro result ref；本地回放投影恒带
   `prefilter_only` 标注。
6. 替代数据源未确认的 mission 不能进入候选预算消耗；确认后替代来源在投影与证据视图中
   可见。
7. `arc/` 生产路径代码中不存在契约替身分支；Live / 订单 / 资金副作用计数为零。
8. `./scripts/check.sh` 通过；新增测试覆盖上述 1–6 的每一条。

## Verification

```bash
uv run pytest tests/test_arc_evidence_source.py -q
uv run pytest tests/test_arc_provider_hypothesis.py -q
uv run pytest tests/test_arc_real_bitpro_path.py -q
uv run pytest tests/test_arc_hollow_claims.py tests/test_arc_acceptance.py tests/test_arc_router_auth.py -q
./scripts/check.sh
git diff --check
```

生产 canary 必须保存真实 Provider 调用记录（model / request_hash）、真实 BitPro
strategy / backtest / result / paper instance 引用与证据窗口 `source_hash`。任何引用缺失都
保持 `needs_data` / `needs_operator`，不得补造。

## Handoff

本合同关闭后的下一优先级：

1. **证据口径统一**：明确 BitPro 回测与本地回放谁的指标是晋级真相，合并或显式分层
   （当前只做标注，两引擎并存）。
2. M0 Handoff 第 1 步：现有 BitPro Paper 策略进化，Challenger 与 Champion 同口径比较。
3. Research Trigger（Sprint 103 资产）接入 ARC 起预算研究。
4. README 与 spec 的能力表述对齐（去 "SOTA" 化），旧路径（kernel / graph / runtime 双轨）
   降级为只读诊断并标 deprecated。
5. 以上稳定后，由产品所有者决定是否重新批准 Sprint 132–134。
