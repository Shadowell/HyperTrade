# User-Directed Contract — 自进化加固：实效、告警与判定质量

> 状态：Active（Delivered，2026-09-14）。
>
> 激活原因：产品所有者 2026-09-14 确认按优先级依次落地三件加固——
> ① 自主进化效果账本；② 数据缺口告警与不可自愈阻塞升级；③ 基准相对退化判定。
> 设计详见[架构 63](../architecture/63-evolution-effectiveness-alerts-and-benchmark.md)。
>
> 前置关系：可插拔市场目标 Phase 1（Delivered）。本合同不改变评审/供给/预算
> 任何权限边界，不触碰 Live；退化口径变化（基准相对）随配置可回退绝对口径。

## Goal

> 自进化系统能否自证：建议有没有赢（效果账本）、有没有被静默卡住（告警）、
> 判断"退化"时是否分得清策略变差与大盘下跌（基准相对）？

## User-Visible Outcome

1. `GET /api/v1/arc/evolution/effectiveness`：周期/任务/证据/决策/结果/成本/
   逐来源的确定性账本，含基线胜率（样本不足时明确不给）与
   `causal_conclusion=not_established`。
2. `GET /api/v1/arc/evolution/alerts`：operator 阻塞立即告警、证据停摆超 72h
   升级告警、连续 3 周期 error 告警；条件消失自动解决；`POST
  /evolution/alerts/{id}/ack` 确认；配置 webhook 后飞书投递（未配置只记台账）。
3. 退化诊断的 window 载荷含 `degradation_basis` 与基准块；大盘普跌不触发研究，
   跑输市场才触发；基准不可用时回退绝对口径并显式标注。

## In Scope

- Slice 1（Delivered）：`arc/effectiveness.py` + `GET /evolution/effectiveness`；
  无效对比单列、胜率仅在有效对比时给出。
- Slice 2（Delivered）：`readiness` 的 resolution/attention_required 分类；
  `arc/evolution_alerts.py` + 表 `arc_evolution_alerts`（迁移 0046）+ 三规则 +
  自动解决 + ack + 飞书投递 + worker 接线 + `GET/ POST /evolution/alerts`。
- Slice 3（Delivered）：`PaperFeedbackPolicyV1.benchmark_relative`、
  `EvolutionConfig.degradation_basis`、`collect_windows` 基准构建与回退标注、
  `evaluate_windows` 相对口径与 reasons、反馈子任务传递候选标的/周期。
- 文档同步：架构 63、本合同、spec、progress、文档索引。

## Out of Scope

- BitPro 面板对账本/告警的展示与代理（后续小切片）。
- 告警升级策略（值班轮转、短信/电话）与告警抑制窗口的可配置化。
- 组合层基准（组合 vs 成分等权）与多标的策略基准；当前多标的走绝对口径。
- 告警"自动修复"动作（如自动重采/重启上游）——本层只观察与通知，不执行修复。

## Safety Boundaries

1. 效果账本只读本地账本，无外部调用与写动作；不产生任何晋级/审批语义。
2. 告警投递可选且显式配置；告警层无审批/交易权限；投递失败不得阻塞扫描。
3. 基准构建失败必须回退绝对口径并标注，绝不静默、绝不因基准缺失停摆或放行。
4. 基准相对为默认口径但可经 `degradation_basis=absolute` 一键回退；绝对口径
   的既有 reason 码与行为保持不变（测试钉死）。
5. 不降低任何数据门槛（14 天窗口/成交数/证据完整性/预算）与评审双门禁。

## Done Means

1. `tests/test_evolution_effectiveness.py`（5 项）、`tests/test_evolution_alerts.py`
   （9 项）、`tests/test_benchmark_relative.py`（9 项）全绿。
2. 既有反馈/延续/进化套件零回归（绝对口径行为保持）。
3. 迁移 0046 建/删表测试通过。
4. `./scripts/check.sh` 通过。

## Verification

```bash
uv run pytest tests/test_evolution_effectiveness.py tests/test_evolution_alerts.py \
  tests/test_benchmark_relative.py tests/test_paper_feedback.py \
  tests/test_evolution_continuation.py tests/test_arc_evolution.py -q
./scripts/check.sh
```

生产验证：`GET /evolution/effectiveness` 返回零账本（尚无闭环任务）与
`win_rate=null`；`GET /evolution/alerts` 在数据缺口阻塞超 72h 后出现
`evolution_evidence_stalled`（tracking 先行）；下一轮真实扫描的 window 载荷
带 `degradation_basis=benchmark_relative`。

## Handoff

- BitPro 侧小切片：代理 + 面板展示 effectiveness 与 alerts。
- 首个真实自主闭环完成后：用效果账本做首轮复盘（胜率/成本/战果），
  结果入 progress。

## 2026-09-21 修订：告警可靠性

用户要求阻塞必须可见。本节取代七天后放弃及同条件只发送一次：未解决未确认每日提醒，失败六小时节流持续重试，确认后不再提醒同原因。飞书HTTP成功必须同时有明确业务成功码；旧记录保留但标为历史回执未验证。列表优先未解决，通知包含中文原因/下一步/时间条件，恢复重现清除旧尝试。BitPro告警入口与高频读取按 specs/001-evolution-alert-reliability 跟踪。

最新完成的手动诊断若同政策revision、三小时内且比自动观察更新，可更新告警投影；不写研究资格/准入账本，不创建研究。修复后可及时解除旧读取告警，无需等待下一小时扫描。

2026-09-22 诊断范围修订：`strategy_ids` 同时约束正常清单行、不可用清单行、当前预览告警和旧延续告警。清单返回不可用行或会话快照未能读取时沿用 `recent_read_unavailable` 分类与固定中文重试提示，不推断原会话身份/起点已丢失；快照已返回却缺字段仍按原门槛阻断。范围外告警按已有恢复规则解决，不修改原Paper与生产策略范围。

边界补充：缺失/非法清单ID作为不可归属的单条覆盖缺口，不建立策略告警且不阻断有效范围；已返回快照但适配器拒绝其身份/格式时使用固定契约错误分类和核对行动，不降为临时传输失败。返回快照的版本缺口仍按原身份阻塞处理。
