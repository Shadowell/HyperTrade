# 63 进化加固：效果账本、数据缺口告警与基准相对退化

> 状态：已交付（2026-09-14）。三个模块共同回答一个问题的三个面——
> 自进化"有没有用、有没有卡住、判断得对不对"。

## 1. 背景

2026-09 生产观察给出三个缺口：

1. **实效无法回答**：周期账本记录了"做了什么"，但"建议胜率、成本、累计
   战果"没有任何聚合面——9 月 18 日首轮真实闭环跑起来后也无从评估。
2. **静默停摆**：一个 8 小时数据缺口让全部老策略的证据构建返回 unavailable，
   持续两周无人知晓，靠人工逐条排查才发现。
3. **绝对口径误报**：退化判定比较策略自身两周的绝对收益/回撤；大盘普跌时
   每个策略都会被判"退化"，研究预算会被市场行情白白消耗。

## 2. 效果账本（`evolution_effectiveness.v1`）

`hypertrade/arc/effectiveness.py`，只统计进化循环发起的任务
（`goal.evolution_context` 或 `feedback_parent`），全部为已持久化回执的
确定性计数：

| 组 | 内容 |
|---|---|
| 周期 | 按状态分布（queued/scanning/no_action/research_created/deferred/source_changed/error…），预算准入回执单列 |
| 任务 | 总数、完成/失败/待处理/进行中 |
| 证据 | 候选数、开发运行与通过、最终运行与通过、基线同窗对比数与胜出数 |
| 决策 | Paper 通过/否决/观察中/效果未知 |
| 结果 | 已结算 `StrategyOutcome` 及其类型分布 |
| 成本 | 候选/模型调用/回测（任务预算用量），准入任务数 |
| 逐来源 | 每个策略的准入任务、退化/主动触发、胜出、观察中、已结算 Outcome |

诚实性：无效对比（`comparison_evidence_invalid`）单独计数、不静默算负；
`baseline_win_rate` 仅在有有效对比时给出；`causal_conclusion=not_established`，
报告自述"样本量小时不足以支撑结论"。面：`GET /api/v1/arc/evolution/effectiveness`。

## 3. 数据缺口告警（`arc_evolution_alerts`）

### 3.1 阻塞分类

`readiness()` 的每个 blocker 新增 `resolution`：`time`（等待自愈：窗口滚动、
成交累积、预算冷却）或 `operator`（需要人工/上游修复：session_identity、
session_start、running_state，以及读取/成本类采样失败
`recent_read_unavailable`/`cost_metadata_unavailable`/`session_identity_missing`）。
延续记录顶层新增 `attention_required`。旧记录缺字段时由同一分类函数兜底。

### 3.2 告警规则（`hypertrade/arc/evolution_alerts.py`）

| 规则 | 条件 | 级别 |
|---|---|---|
| `evolution_blocked_needs_operator` | 任一 operator 阻塞 | warning，立即 |
| `evolution_evidence_stalled` | evidence_recheck 且 `next_eligible_at` 为空（无法预计何时恢复），先 tracking，持续 >72h 升级为告警 | warning |
| `evolution_cycles_erroring` | 最近 3 个扫描周期全部 error | critical |

同一策略已有 operator 告警时不再叠加 stalled 跟踪（去噪）。**陈旧延续记录
（>3 小时未刷新，说明策略已暂停/移除、扫描不再更新它）不参与告警**——策略被
暂停时其未解决告警会自动 resolved，暂停中的策略不会被误报。确定性 ID 去重；
条件消失自动 `resolved`；`GET /evolution/alerts` 查看、`POST
/evolution/alerts/{id}/ack` 确认（确认后同一条件不再打扰，条件消失自动解决，
再次出现视为新事件重新告警）。投递复用 `FEISHU_WEBHOOK_URL`（未配置只记台账，
且不计为一次投递尝试——webhook 配置后下个评估周期立即送达；失败 6 小时节流
重试、7 天放弃）；worker 每个 tick 评估，投递失败永不阻塞扫描。

## 4. 基准相对退化

### 4.1 口径

策略两周变化 − 其标的买入持有两周变化 = 相对退化（pp）。买入持有序列用
`market_klines` 在相同 [start, end] 窗口构建（边界容差 = 周期长度）；触发条件
`max(relative_return_drop_pp, relative_drawdown_increase_pp) ≥ threshold_pp`，
reasons 为 `relative_return_drop`/`relative_drawdown_increase`。

### 4.2 回退与标注（绝不静默）

| 基准状态 | 含义 | 行为 |
|---|---|---|
| observed | 序列可用 | 相对口径触发判定 |
| unavailable | 拉取失败/点数不足 | 回退绝对口径，window 载荷标注 |
| misaligned | 边界超出容差 | 同上 |
| insufficient_coverage | 15m 等周期超出单页 1000 根，无法覆盖 14 天 | 同上 |
| unsupported_timeframe | 未知周期粒度 | 同上 |
| （多标的策略） | 无单一标的不取基准 | 绝对口径 |

`PaperFeedbackPolicyV1.benchmark_relative`（默认 True）随 goal 冻结；
`EvolutionConfig.degradation_basis`（默认 `benchmark_relative`）由操作员控制；
反馈子任务传递候选的标的与周期。

## 5. 安全与兼容

- 效果账本只读本地账本，无外部调用、无写动作。
- 告警投递仅在显式配置 webhook 后发生；内容为固定模板文本；告警层不持有
  任何审批/交易权限。
- 基准序列为只读行情读取（PacedReadClient 节流）；构建失败回退绝对口径保持
  旧行为，绝不因基准缺失而停摆或放行。
- 既有 reason 码（return_drop 等）在绝对口径下不变；已有测试全部保持。

## 6. 验证

```bash
uv run pytest tests/test_evolution_effectiveness.py tests/test_evolution_alerts.py \
  tests/test_benchmark_relative.py tests/test_paper_feedback.py \
  tests/test_evolution_continuation.py tests/test_arc_evolution.py -q
./scripts/check.sh
```

生产面：`GET /evolution/effectiveness`、`GET /evolution/alerts`；BitPro 面板
接入（代理 + 展示）作为后续小切片。
