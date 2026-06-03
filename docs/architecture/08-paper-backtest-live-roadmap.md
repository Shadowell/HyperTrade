# 08 Paper, Backtest, Live Roadmap / 后续交易闭环

## English

Sprint 01 intentionally stops before autonomous trading. Later sprints add:

- paper trading autorun with pause control
- max 10 positions, 20% per symbol, max 5x leverage
- long/short rule signals with agent explanation
- next-tick fill model, 5 bps taker fee, 2 bps slippage
- Strategy SDK and Backtrader research/backtest loop
- Testnet order intent and human approval

Runtime strategy files are written under `/opt/hypertrade/workspace/strategies`, not into the git source tree.

## 中文

Sprint 01 故意停在自动交易之前。后续 Sprint 增加：

- 自动模拟盘，且 `/harness` 可暂停
- 最多 10 个持仓，单标的 20%，最大 5x
- 多空规则信号，Agent 负责解释
- 下一 tick 成交，taker 5 bps，滑点 2 bps
- Strategy SDK 和 Backtrader 策略研究/回测闭环
- Testnet 订单意图与人工审批

运行时策略文件写入 `/opt/hypertrade/workspace/strategies`，不写入 git 源码树。

## Sprint 03 Implementation / Sprint 03 实现

Sprint 03 adds a small built-in strategy lab:

- `strategy_research` stores free-form research prompts, built-in strategy keys, Markdown reports, and structured specs.
- `backtest_runs` stores Backtrader results with start cash, end value, return percentage, max drawdown, trade count, Markdown, and JSON.
- `momentum_breakout_v1` is the first deterministic Strategy SDK template.
- `/api/strategy/research` and `/api/backtests` provide the research-to-backtest loop.
- `/harness` shows the latest strategy research and latest backtest metrics.
- Sprint 13 adds optional OKX REST candle input for Backtrader through
  `use_live_candles`, `symbol`, `bar`, and `candle_limit`.
- When live candles are enabled, `backtest_runs.report_json` records `data_source`,
  `inst_id`, `bar`, and `candle_count`.

Sprint 03 增加一个小型策略实验室：

- `strategy_research` 保存自由文本研究主题、内置策略 key、Markdown 报告和结构化 spec。
- `backtest_runs` 保存 Backtrader 结果：初始资金、结束权益、收益率、最大回撤、成交数、Markdown 和 JSON。
- `momentum_breakout_v1` 是第一个确定性的 Strategy SDK 模板。
- `/api/strategy/research` 与 `/api/backtests` 提供研究到回测的闭环。
- `/harness` 展示最新策略研究和最新回测指标。
- Sprint 13 增加可选的 OKX REST K 线回测输入，通过 `use_live_candles`、`symbol`、
  `bar` 和 `candle_limit` 控制。
- 启用 live candles 时，`backtest_runs.report_json` 会记录 `data_source`、`inst_id`、
  `bar` 和 `candle_count`。

## Sprint 28-30 Update / Sprint 28-30 更新

- RiskEngine now validates live/testnet order intents before creation approval and execution.
- Mainnet execution is blocked; Testnet execution requires approval and a passing risk check.
- OKX Testnet signed execution supports market/limit buy/sell SWAP orders through
  `/api/live/order-intents/{id}/execute` and CLI `/live execute <id>`.
- Strategy experiments persist a multi-step workflow: hypothesis, data selection, backtest,
  critique, revision suggestion, and report.

- RiskEngine 现在会在创建、审批、执行前校验 live/testnet order intent。
- Mainnet 执行保持阻断；Testnet 执行必须先审批并通过风控。
- OKX Testnet signed execution 支持 market/limit、buy/sell、SWAP 订单，通过
  `/api/live/order-intents/{id}/execute` 和 CLI `/live execute <id>` 使用。
- 策略实验会持久化多步骤 workflow：hypothesis、data selection、backtest、critique、
  revision suggestion、report。
