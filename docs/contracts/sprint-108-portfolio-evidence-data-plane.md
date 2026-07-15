# Sprint 108 - Portfolio Evidence Data Plane

> 状态：Active；2026-07-15 在 Gate F 通过后自动进入实施。

## Goal

为 StrategyCard V2 候选建立可复现、有界、来源绑定的组合观察窗口，使相关性、波动、回撤、
共同暴露、容量与流动性结论都附带样本数、时间范围、freshness 和 unknown reason；完整权益/
收益序列继续由 BitPro 持有，HyperTrade 不因此获得任何 paper/live/订单写权限。

## In Scope

- `PortfolioObservationWindowV1`、`PortfolioDataQualityV1` 与策略/配对统计 schema。
- 只通过 BitPro MCP `paper_snapshot`、`paper_equity_curve` 等已批准 read contract 采集。
- 固定 30/60/90 天 horizon、UTC bucket、每策略最多 500 点的内存内归一化与统计。
- 策略级 return/volatility/drawdown proxy、方向/标的/周期/因子共同暴露；配对同步相关性。
- capacity/liquidity/risk-contribution proxy 的完整输入门禁与显式 unknown。
- immutable summary persistence、source refs/content hash、幂等 capture 和历史查询/diff。
- PortfolioAssessment V2 消费已持久化窗口，不再自行把 MonitorSnapshot 当收益序列。
- 管理员 API、CLI、Textual Portfolio 和 Web Portfolio 共享服务端窗口/质量投影。

## Out of Scope

- 在 HyperTrade PostgreSQL 保存完整 BitPro equity、return、position、trade 或 order 序列。
- 直连 BitPro 数据库、复制 BitPro 业务逻辑，或在 MCP contract 缺失时旁路补数据。
- 自动 paper start/pause/promote/retire、live order、资金分配、调仓或风险预算修改。
- VaR/CVaR、收益优化器、新时序数据库、无界历史拉取或单一收益率策略排名。
- Sprint 109 的 Champion–Challenger cohort 和 Sprint 110 的 shadow weights/proposals。

## Technical Plan

1. 定义 strict Pydantic 合同：request 固定 horizon、bucket、card ids、max points、freshness、
   min aligned returns；所有 Decimal 以字符串序列化，UTC 时间必须带时区。
2. Alembic `0020` 新增 immutable observation window 表，持久化 request/policy/source/content
   hash、状态、窗口边界、质量报告、策略统计、pairwise 统计和 created_by；不持久化原始点。
3. 新建 read-only adapter protocol，仅允许 `health`、`paper_snapshot`、
   `paper_equity_curve`；capture 前先做 capability/health preflight，缺失或异常转为 data gap。
4. 从 Card V2 的 Manifest/version/BitPro strategy refs 选择候选。没有 paper identity 的 Card
   仍进入 denominator，并输出 `paper_identity_unavailable`，不得从名称猜 strategy id。
5. 每个有 identity 的候选只拉一次 bounded curve/snapshot；在内存中解析 UTC、去重、按
   horizon 截断和 bucket 对齐，拒绝未来时间、无效 Decimal、非单调/重复或超限输入。
6. 使用 Decimal 计算逐桶收益、样本覆盖、年化前波动 proxy、peak-to-trough drawdown；
   risk contribution 只在至少两个可用策略、同步样本和组合权重事实完整时输出，否则 unknown。
7. 配对统计只使用相同 bucket 的同步收益；样本不足、零方差、时间错位、来源 stale/unhealthy
   时 correlation 保持 unknown，并附 sample count/start/end/source ids/reason。
8. capacity/liquidity 只读取 source-bound snapshot/Card evidence；缺任一字段不做估算。
   direction/factor 仅使用 Card/Manifest 声明，不能根据收益曲线推断。
9. canonical request + source content hash 形成幂等键边界；相同输入复用窗口，来源变化生成新
   immutable row。API 不允许客户端上传统计结果或 source payload。
10. PortfolioAssessment 只读取选定/最新窗口的服务端统计摘要，引用 window id/content hash；
    没有窗口、窗口不足、窗口 stale 和窗口可用必须呈现为不同状态。
11. FastAPI 提供 capture/list/get/diff；CLI `/windows`、Textual/Web Portfolio 展示覆盖率、
    freshness、unknown 和 pairwise 证据，不在客户端重算。
12. 添加 schema、纯函数、幂等、stale/misaligned/zero-variance/invalid timestamp、500 点上限、
    PostgreSQL migration、API/UI、PortfolioAssessment 集成和 forbidden-import/dispatch 测试。

## Done Means

- 每张 V2 Card 都出现在 observation denominator；无 BitPro paper identity 时明确 needs_data。
- 每个可用指标公开 horizon、bucket、sample count/start/end、freshness、source refs 和 hash。
- 时间错位、样本不足、零方差、来源不健康/stale 或无效数值均失败关闭，不产生伪精度。
- PostgreSQL 仅有窗口级 refs/统计/质量，不含 `equity_curve`、returns array、position/trade/order。
- 相同 request/source 重放幂等；source 变化追加新窗口，历史 content hash 不变。
- PortfolioAssessment 引用窗口统计并区分 no_cards/no_window/insufficient/stale/available。
- API、CLI、Textual、Web 使用同一服务端投影，客户端无统计或质量判定算法。
- 静态与运行时测试证明 capture 无 BitPro mutation、paper lifecycle、live/order/capital 路径。
- PostgreSQL upgrade/downgrade/upgrade、`./scripts/check.sh` 和生产 read-only smoke 通过。

## Verification

```bash
uv run pytest tests/test_portfolio_observation_windows.py -q
uv run pytest tests/test_portfolio_assessment_v2.py tests/test_strategy_card_v2.py -q
uv run pytest tests/test_tui_app.py tests/test_cli.py -q
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
./scripts/check.sh
```

Manual/production checks:

- 对 no-card、Manifest-only、可用 paper curve、样本不足、错位和 stale fixtures 检查状态。
- 重复 capture 确认 window 幂等；改变 source hash 后只追加 summary row。
- 审计数据库 JSON，确认没有完整 equity/return/position/trade/order array。
- 对比 capture 前后 PaperPromotion、paper order、live intent 和 worker action 计数。
- 生产缺少可用 paper identity 时返回 `needs_data`，不得为了验收创建或启动 paper。

## Risks / Notes

- 当前 BitPro `paper_equity_curve` 返回 bounded samples，但可能不带不可变 snapshot id；本
  Sprint 使用 canonical response digest + contract/tool refs 作为 source hash，不伪造 BitPro id。
- 现有生产 Card 可能全部没有 paper identity；这应验证 no-window 失败关闭，而非构造数据。
- 旧 PortfolioAssessment 的 MonitorSnapshot correlation 是历史事实；新 assessment 使用 window
  ref，不能回写或重算旧 assessment。
- 所有统计均为研究证据 proxy，不表示策略质量、盈利概率或资金权重。

## Handoff

- Gate G 的 evidence 部分通过后，Sprint 109 才能使用 `available` 且口径一致的窗口构建
  Champion–Challenger paper cohort。
- 若 BitPro read contract 无法提供时间/身份/point limit 等必要字段，记录 dependency 并保持
  unknown，不扩张为数据库访问或执行权限。

## Implementation Record

- `0020_portfolio_windows` 新增单一 immutable summary 表；保存 request/source/content hash、
  质量报告、策略与 pairwise 统计，不保存 equity/return/position/trade/order 序列。
- `PortfolioEvidenceService` 只暴露 health、paper snapshot、bounded equity curve read adapter；
  Manifest-only Card 仍计入 denominator，缺 paper identity 时不 dispatch BitPro read。
- UTC/bucket/horizon 归一化、Decimal returns/volatility/drawdown/correlation、freshness、样本数、
  source digest 和 unknown reason 均在服务端计算；capacity/liquidity/risk contribution 缺事实
  时保持 unknown。
- 同一 request/source/quality projection 重用既有窗口；来源或质量变化才追加行。capture time
  仅为审计元数据，不能制造定时 snapshot 风暴。
- PortfolioAssessment 改为引用 observation window id/content hash，旧 assessment 保持不可变；
  API、CLI `/windows`、Textual 和 Web Portfolio 使用同一服务投影。
- 临时 PostgreSQL 通过全链升级、`0020 -> 0019 -> 0020` 和表存在性检查；完整
  `./scripts/check.sh` 通过 frontend lint/9 tests/build、Ruff、mypy（145 source files）与
  505 Python tests。生产 migration/read-only smoke 尚待部署。
