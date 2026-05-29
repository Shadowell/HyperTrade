# 07 OKX Market Data / OKX 行情

## English

Sprint 01 targets all OKX perpetual swap instruments (`SWAP`). Mainnet market data is used, while trading remains Testnet-only in later sprints.

Data flow:

1. Worker subscribes to public WebSocket tickers with `instType=SWAP`.
2. REST tickers run at startup and then every 5 minutes as a supplement.
3. REST tickers are also used as fallback after repeated WS failures.
4. Parsed tickers are upserted into `market_tickers`.
5. The agent reads latest movers from PostgreSQL when the user asks for a summary.
6. The agent reads one exact `market_tickers.inst_id` when the user asks for a specific listed
   symbol through the `market_ticker` tool.
7. The agent fetches recent candles from OKX REST on demand for `market_candles`; Sprint 10 does not
   persist historical candles.
8. The agent reuses candle summaries across several symbols for `market_compare`; Sprint 11 ranks
   symbols without persisting the comparison result separately.

Raw ticker snapshots are retained for short-term operational use; aggregated summaries are kept long term.
Candles are used as short-lived research input only in Sprint 10.

## 中文

Sprint 01 覆盖 OKX 全市场永续合约 `SWAP`。行情使用 mainnet；交易在后续 Sprint 中默认只走 Testnet。

数据流：

1. worker 订阅 public WebSocket tickers，参数 `instType=SWAP`。
2. REST tickers 在启动时跑一次，之后每 5 分钟补充一次。
3. WS 连续失败后也用 REST tickers 降级。
4. 解析后的 ticker upsert 到 `market_tickers`。
5. 用户发起归纳时，Agent 从 PostgreSQL 读取最新异动。
6. 用户询问具体已上线标的时，Agent 通过 `market_ticker` 精确读取一个
   `market_tickers.inst_id`。
7. 用户询问走势或 K 线研究时，Agent 通过 `market_candles` 按需从 OKX REST 获取近期 K 线；
   Sprint 10 不持久化历史 K 线。
8. 用户询问多标的强弱比较时，Agent 通过 `market_compare` 复用多个标的的 K 线摘要；
   Sprint 11 不单独持久化比较结果。

原始 ticker 用于短期运行，聚合摘要长期保留。
K 线在 Sprint 10 中只作为短生命周期研究输入。
