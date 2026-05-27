# 07 OKX Market Data / OKX 行情

## English

Sprint 01 targets all OKX perpetual swap instruments (`SWAP`). Mainnet market data is used, while trading remains Testnet-only in later sprints.

Data flow:

1. Worker subscribes to public WebSocket tickers with `instType=SWAP`.
2. REST tickers are used as fallback after repeated WS failures.
3. Parsed tickers are upserted into `market_tickers`.
4. The agent reads latest movers from PostgreSQL when the user asks for a summary.

Raw ticker snapshots are retained for short-term operational use; aggregated summaries are kept long term.

## 中文

Sprint 01 覆盖 OKX 全市场永续合约 `SWAP`。行情使用 mainnet；交易在后续 Sprint 中默认只走 Testnet。

数据流：

1. worker 订阅 public WebSocket tickers，参数 `instType=SWAP`。
2. WS 连续失败后用 REST tickers 降级。
3. 解析后的 ticker upsert 到 `market_tickers`。
4. 用户发起归纳时，Agent 从 PostgreSQL 读取最新异动。

原始 ticker 用于短期运行，聚合摘要长期保留。

