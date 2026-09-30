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

2026-09-22 投递事件修订：同一策略/告警码在 open 期间若阻塞条件签名改变，立即开启新事件并尝试发送新文案，不沿用旧的24小时提醒或失败节流。成功回执必须绑定当时的条件签名和消息哈希；缺绑定的旧回执及当前消息已变化的回执均显示未核验，不倒填历史。同条件提醒、失败重试、确认和恢复规则保持原口径。

升级兼容：open且旧成功回执缺少内容绑定时，跳过该旧回执的24小时送达节流，对当前内容做一次真实重投；旧接受时间、结果与业务码保留为未绑定历史观察，不猜旧签名。新重投失败后按正常6小时节流，确认状态不重投；已有完整绑定而仅文案变化仍守原24小时提醒。

## 2026-09-30 BitPro 名称准入补充

研究自测与模拟孵化在外部创建前校验 BitPro 名称协议：资产、周期、类型、标的范围、可读方法和有限正数资金。机器代号/长哈希仅保留在描述与操作身份，非法名称返回 `bitpro_strategy_name_invalid`，不执行远端校验、创建、配置或启动。无审核研究也使用规范名称；孵化的名称与配置共用原始小数资金，不向下取整。BitPro 为最终准入事实源，客户端协议校验不提供交易退出、重启恢复或审核证明；#1168 的退出执行/生成器完整对齐仍待独立验证。

## 2026-09-30 远程历史窗口

ARC 默认使用 RemoteWindow，经 KlineDataProvider 获取 BitPro 的 market_history_page.v1。固定闭合边界，每页最多5000根，总计最多20000根；先验证服务/标的/周期身份、SHA256、完整时间网格、价格和新鲜度，再作为研究输入。60秒缓存绑定服务和凭据摘要，不跨目标或边界复用；缓存损坏/过期必须读远端。默认不读宿主机目录或旧 SQLite；明确离线 bitpro_archive 路径继续可用，容器不再挂载 /bitpro-data。

## 2026-09-30 组合范围声明

显式symbols需为非空字符串列表；空数组、字符串冒充数组或空成员均拒绝，不用单一scope替代。未声明symbols时保留历史单标的继承。原策略动态selection_logic、trade_symbols及全量行情feed必须随基线保留，并由BitPro冻结执行身份与同窗行情校验。

## 2026-09-30 生成策略双退出与会话恢复

生成器强制有限正数止损、止盈，参数搜索不能关闭任一保护；运行态检查覆盖错误类型、非有限值和会话/参数不匹配。真实high/low先判止损，再判止盈；跳空止损按更差开盘价成交。生成源码遵守arc_generated.v1，并通过BitPro必要写入回调在订单前持久化pending、确认后保存持仓保护和时钟；持仓时限包含停机经过的bar时长，预热不重放交易。

自测/孵化创建前在本地验证生成代码合同和退出参数，传递同一份research_parameters及顶层保护字段、资金和周期。旧的无恢复合同生成候选不能沿用旧“validated”状态直接创建。源代码/原生基线仍依照其独立来源合同与平台校验，不伪造重新回测或强改已有Paper。

## 2026-09-30 双层观察窗口与缺口语义

默认开启短期观察：3日（可设3–5日）或同一会话10笔交易，以真实小时权益观察到至少15个百分点回撤作为研究信号；零权益按已观测全损处理。身份/版本/费用、分页、时间边界及新鲜度不明时拒绝。冷启动显示已观察冲击，但不满足年龄/交易门槛时不创建研究。内部连续缺口最多8小时、短窗覆盖至少80%，展示补点带imputed，收益/回撤只用观测值。

长期严格7+7读取仍为首选；发生采样缺口时，可读取14日聚合窗口，要求年龄与原最少交易数、95%覆盖、真实起中终边界及最多8小时连续缺口。只按真实周边界净收益差发起研究，不估算完整回撤或相对基准Alpha。状态与回执为observed_weekly_returns.v1，与完整窗口分开。

短期紧急通道必须有受控来源变体政策，保持原风险参数、完整标的、预算、冷却与Paper审核；不直接采纳或启用实盘。持久续跑和验收分别使用trigger_short_horizon / trigger_observed_7_plus_7 / trigger_7_plus_7，不伪装14日完整证据。观察设置可关闭，原长窗规则保留。

代码校验默认通过研究权限POST /strategies/validate-code，沿用平台校验合同；显式注入的MCP传输仍兼容，默认不再依赖通用MCP入口的POST权限。
