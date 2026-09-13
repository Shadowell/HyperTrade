# User-Directed Contract — 可插拔市场目标与自进化通用化

> 状态：Active（Phase 1 Delivered，2026-09-14）。
>
> 激活原因：产品所有者 2026-09-14 明确——自进化默认打开；自进化功能必须通用，
> 通过 MCP 对接目标平台；BitPro 是首个目标（MCP 自进化），QuantLab（A 股/美股）
> 后续提供 MCP 后应可直接插入；归因升级与元学习（阈值/预算离线自调）同步推进；
> 更新文档并清理无用代码。
>
> 前置关系：进化闭环 M0（Delivered）、全自动 Paper 评审（Delivered）。本合同
> 不改变任何判定阈值语义、不触碰 Live 边界；设计详见
> [架构 62](../architecture/62-pluggable-market-targets.md)。

## Goal

回答一个问题：

> 自进化核心能否在**不修改代码**的前提下更换市场平台——今天跑 BitPro，明天经
> 标准 MCP 契约接入 QuantLab——同时让阈值这类参数能从已结算的历史里离线自调，
> 并保持全部证据与审计语义不变？

## User-Visible Outcome

1. `GET /api/v1/arc/evolution` 的配置含 `target_id`；`MARKET_TARGET` 设置切换
   活跃目标；未注册目标在 `PUT` 配置时被拒绝并给出已注册清单。
2. `GET /api/v1/arc/evolution/tuning` 返回 `evolution_tuning.v1` 建议报告
   （样本数、p50/p90/最大值、建议阈值与否决理由）；每天至多一条
   `meta_tuning` 周期回执；授权后才应用且每次一步、可审计。
3. 归因面板的 `costs`/`long_short` 维度在上游（`coverage.fields`）显式见证后
   点亮并附数值；未见证时维持 unknown，绝不从裸 PnL 推断。
4. QuantLab 类平台按七个规范 MCP 工具实现后，`preflight()` 逐个校验缺项，
   注册即成为可选目标。

## In Scope

- **目标注册层（Slice 1，Delivered）**：`hypertrade/targets`——`market_target.v1`
  档案、注册表、BitPro 内置目标、`market-evolution.v1` 通用 MCP 契约与
  `McpContractClient`、Phase 2 类型化端口（`ports.py`）。
- **绑定与默认开启（Slice 2，Delivered）**：进化循环客户端经注册表解析；
  `readiness()` 窗口由目标日历参数化（continuous/UTC/14 天与旧行为一致）；
  `EvolutionConfig.enabled` 默认 True；`target_id` 配置期校验。
- **离线元学习（Slice 3，Delivered）**：`arc/meta_tuning.py`——回放已结算
  7+7 观测，阈值=观测 p90 规则，边界 [5,20]pp、单步 ≤3pp、每日一次、默认仅
  建议、自动应用需显式授权并经受审计的 configure。
- **归因见证式升级（Slice 4，Delivered）**：costs/long_short 仅在双页
  `observed` 见证 + 条目数值齐备时点亮；状态三态 unknown/observed/unverified。
- **清理与文档（Slice 5，Delivered）**：`_memory` 死返回值与重复活跃/阻塞计算
  删除；架构 62、本合同、spec 同步。

## Out of Scope

- Phase 2 端口化：`_scan` 五个读取面、`strategy_return_series.v1` 强断言、
  成本身份词表、Paper 供给三段写路径迁移到 `targets/ports.py` 类型化端口。
- `sessions` 日历的按交易日计数窗口（当前 continuous 日历完整支持；sessions
  档案可注册但窗口仍按自然日取整，Phase 2 修正）。
- BitPro 服务端暴露规范工具名（HyperTrade 侧契约已就绪，BitPro 侧另行立项）。
- QuantLab 实机接入与 A 股/美股数据、成本、交易规则适配（需要 QuantLab 提供
  MCP 后才开始）。
- `proactive_enabled` 默认值变更；预算上限（max_research_per_day 等）的自动
  调整——本期元学习只覆盖退化阈值。

## Safety Boundaries

1. 不改变任何判定语义：数据门槛、7+7 口径、成功判据、评审双门禁均不变；
   `enabled` 默认翻转只影响新建配置，已持久化配置与 revision 不受影响。
2. 元学习默认只建议；自动应用必须 `meta_tuning_auto_apply=true`、单步 ≤3pp、
   在校验边界内、每日一次，且经 `EvolutionService.configure` 修订审计，
   操作者固定为 `hypertrade:meta-tuner`；任何绕过 configure 的写入即缺陷。
3. 归因不推断：见证缺失时维度必须保持 unknown；`causal_conclusion` 恒为
   `not_established`；投影只允许经数值校验的台账条目。
4. 目标层不持有写权限：`live_preflight` 只读；Paper 写动作仍走既有审批与
   收据链（`paper_review_started` 等）；本层不新增任何 Live 通路。
5. 未注册目标必须在配置期拒绝（409），不得进入扫描/研究阶段。

## Done Means

1. `tests/test_market_targets.py`：注册/解析/拒未知/设置驱动切换/契约
   preflight/canonical 路由全绿。
2. `tests/test_meta_tuning.py`：样本不足不调、p90 规则、边界限步、仅建议回执、
   授权应用后 revision/操作者/回执正确、每日幂等、禁用无回执。
3. `tests/test_arc_attribution.py`：既有契约测试（含"费用不得由裸 PnL 推断"）
   保持全绿；新增见证点亮/无值不编造/词表约束测试。
4. `tests/test_arc_evolution.py`：默认开启断言、未注册目标拒绝、目标工厂解析。
5. `./scripts/check.sh` 通过。

## Verification

```bash
uv run pytest tests/test_market_targets.py tests/test_meta_tuning.py \
  tests/test_arc_attribution.py tests/test_arc_evolution.py \
  tests/test_evolution_continuation.py -q
./scripts/check.sh
```

生产验证：`GET /evolution` 含 `target_id=bitpro`；`GET /evolution/tuning` 返回
`insufficient_data`（历史观测尚不足 12 条）直至观测积累；`meta_tuning` 回执在
周期账本可见。

## Handoff

- Phase 2 端口化（本文 Out of Scope 第 1–2 条）作为下一个合同，验收=∑ 端口在
  BitPro 实现下全量测试逐字节等价 + 一个非 BitPro 假目标跑通读取面。
- QuantLab MCP 就绪后：按架构 62 第 9 节五步接入；BitPro 服务端规范工具名可作为
  独立小切片先行。
