# 08 Paper, Backtest, Live Roadmap / 后续交易闭环

## English

Sprint 01 intentionally stops before autonomous trading. Later sprints add:

- paper trading autorun with pause control
- max 10 positions, 20% per symbol, max 5x leverage
- long/short rule signals with agent explanation
- next-tick fill model, 5 bps taker fee, 2 bps slippage
- Strategy SDK and Backtrader
- Testnet order intent and human approval

Runtime strategy files are written under `/opt/hypertrade/workspace/strategies`, not into the git source tree.

## 中文

Sprint 01 故意停在自动交易之前。后续 Sprint 增加：

- 自动模拟盘，且 `/harness` 可暂停
- 最多 10 个持仓，单标的 20%，最大 5x
- 多空规则信号，Agent 负责解释
- 下一 tick 成交，taker 5 bps，滑点 2 bps
- Strategy SDK 和 Backtrader
- Testnet 订单意图与人工审批

运行时策略文件写入 `/opt/hypertrade/workspace/strategies`，不写入 git 源码树。

