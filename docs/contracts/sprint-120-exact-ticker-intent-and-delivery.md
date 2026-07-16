# Sprint 120 — 任意明确合约标的的精确行情交付

> 状态：Closed — 2026-07-16。

## Goal

让操作者的明确单标的行情问题（例如“看下 LAB 的价格”）始终走精确合约查询：存在时交付该标的价格，
不存在时交付该标的的数据缺口；绝不能降级为无关的全市场快照计数。

## In Scope

- 模型先输出受限的结构化输入意图；服务端只接受来自用户原文的明确标的，并将裸符号、`USDT` 和
  `USDT-SWAP` 写法统一为 OKX `BASE-USDT-SWAP` 查询。模型不能选择新工具、权限或操作。
- 当模型不可用、结构不合法或提取的标的不在用户原文中时，受控规则解析兜底。
- 保留概览问题的 `market.summary` 行为；不把英文自然语言、报价币或市场术语误作标的。
- 对精确标的存在与不存在两条路径分别增加规划、工具和公开结论回归。
- 将该真实故障写入独立评测集，验证结论含用户请求的标的和价格或该标的的数据缺口。

## Out of Scope

- 新增交易所、现货/币本位合约、自动刷新或任何订单、策略、资金变更。
- 根据名称、近似匹配或无关快照猜测价格。
- 重新设计完整回答流或外部 BitPro MCP 契约。

## Done Means

- `看下 LAB 的价格` 的计划参数为 `inst_id=LAB-USDT-SWAP`，不读取泛化快照作为答案；模型提取的
  `LAB` 必须可在用户原文中逐字验证。
- 有该快照时公开结论包含 `LAB-USDT-SWAP` 与“最新价”；没有时为 `needs_data`，明确说明
  `LAB-USDT-SWAP` 未找到并提供下一步。
- `现在合约市场整体怎么样` 继续是概览查询，不产生虚构标的。

## Verification

```bash
./scripts/check.sh
HYPERTRADE_EVAL_TARGET=isolated ./scripts/run_operator_task_completion_eval.sh
```

部署后执行只读验收：`ht ask '看下 LAB 的价格'`。若生产行情库没有 LAB，则应返回明确的
`LAB-USDT-SWAP` 数据缺口；若存在，则应返回其最新价。两种情况下都不得出现“已读取 10 个最新合约行情快照”。

## Handoff

已完成：模型受限意图提取只可绑定用户原文中的完整标的 token；服务端仍独占受审查能力、只读范围、依赖和
权限决策。`看下 LAB 的价格` 在生产 Codex Provider 上返回 `LAB-USDT-SWAP` 的最新价和可追溯行情来源，
不再降级为“已读取 10 个最新合约行情快照”。

新鲜 `./scripts/check.sh` 完成：pytest 674 passed；保留 2 个既有、与本 Sprint 无关的 OKX coroutine
warning。专用隔离评测镜像重建后，`operator_task_completion.v1` 100/100 passed、P0=0、P1=0；产物中的
`m03_exact_lab` 结论为 `LAB-USDT-SWAP` 最新价，确认不是旧 `SOL` 案例回放。GitHub 部署工作流
`29507590520` 成功，生产 API 健康检查通过。没有新增下单、策略、资金或主网权限。
