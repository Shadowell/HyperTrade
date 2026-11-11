# 07 OKX Market Data / OKX 行情

## English

Sprint 01 targets all OKX perpetual swap instruments (`SWAP`). Mainnet market data is used, while trading remains Testnet-only in later sprints.

Data flow:

1. Worker subscribes to the public WebSocket `tickers` channel **per `instId`**, not per
   `instType`: OKX documents `channel` and `instId` as the only parameters of that channel, and a
   subscription that is not established gets the connection closed after 30 s (close code 4004).
   The contracts come from a REST snapshot of the SWAP tickers; the `OKX_WS_MAX_INSTRUMENTS` (default
   100) busiest by 24h turnover (`last` x `volCcy24h`) are subscribed, 50 per `subscribe` request.
   The rest keep the REST cadence. Every streamed instrument costs about one `market_tickers` row
   write per second, and OKX publishes no per-connection cap for public channels (only the close
   codes 4008/4009), so a close with 4008/4009 halves the subscription (never below 10) for the
   rest of the process. The URL is `wss://ws.okx.com/ws/v5/public` (port 443): OKX stopped
   accepting port 8443 on 2026-10-31, and a configured `:8443` on an OKX host is rewritten.
2. REST tickers run at startup and then every 5 minutes as a supplement.
3. REST tickers are also used as fallback whenever the WS stream fails. Reconnects back off 15 s,
   30 s, then 60 s and start over after a connection streamed for 30 s. A stream also fails when
   no ticker arrives within 20 s of subscribing or for 30 s afterwards (a keepalive does not
   count), and the failure carries what OKX answered. Keepalive is OKX's text `ping`/`pong`; a
   close with 1000/1001 or OKX's 64008 restart notice reconnects after one second, as no error.
4. Parsed tickers are upserted into `market_tickers` in batches on a worker thread, never on the
   worker's event loop: one transaction per REST snapshot (about 700 tickers), and about one batch a
   second for WS tickers (newest per instrument). Writing them one by one on the loop froze every
   worker loop for 9 s to over a minute.
5. The agent reads latest movers from PostgreSQL when the user asks for a summary.
   Market heat summaries also compute breadth from recent ticker snapshots:
   advancers, decliners, average UTC0 change, and strongest/weakest symbols.
6. The agent reads one exact `market_tickers.inst_id` when the user asks for a specific listed
   symbol through the `market_ticker` tool.
7. The agent fetches recent candles from OKX REST on demand for `market_candles`; Sprint 10 does not
   persist historical candles.
8. The agent reuses candle summaries across several symbols for `market_compare`; Sprint 11 ranks
   symbols without persisting the comparison result separately.
9. Sprint 48 adds `market_intelligence`: a read-only, connector-neutral evidence
   layer that fetches OKX public funding rate and open interest for one SWAP
   instrument, then combines it with deterministic curated context from
   `docs/knowledge/market-intelligence-curated.md`.

Raw ticker snapshots are retained for short-term operational use; aggregated summaries are kept long term.
Candles are used as short-lived research input only in Sprint 10.
Market intelligence results are not trading signals; each result carries
`source`, `source_path`, `symbol`, `as_of`, `freshness_seconds`, `metrics`,
`missing_fields`, and a bounded `sample` so reports can show source-backed
context and unavailable fields without inventing data.

## 中文

Sprint 01 覆盖 OKX 全市场永续合约 `SWAP`。行情使用 mainnet；交易在后续 Sprint 中默认只走 Testnet。

数据流：

1. worker 订阅 public WebSocket 的 `tickers` 频道，**按 `instId` 逐个订阅**，不能按 `instType`：OKX 文档里该频道
   只有 `channel` 和 `instId` 两个参数，订阅没建立成功的连接 30 秒后会被服务端关闭（关闭码 4004）。合约清单来自
   SWAP tickers 的 REST 快照，取 24 小时成交额（`last` × `volCcy24h`）最大的 `OKX_WS_MAX_INSTRUMENTS` 个
   （默认 100），每个 `subscribe` 请求 50 个；其余合约仍按 REST 节奏刷新。每多订阅一个合约，`market_tickers`
   大约每秒多一次行写入；OKX 没有公布公共频道的单连接订阅数上限（只有关闭码 4008/4009），所以收到 4008/4009 时
   把订阅数减半（不低于 10），在进程存活期间保持。地址是 `wss://ws.okx.com/ws/v5/public`（443 端口）：OKX 自
   2026-10-31 起不再接受 8443 端口，配置里写着 OKX 域名加 `:8443` 时会被改写成 443。
2. REST tickers 在启动时跑一次，之后每 5 分钟补充一次。
3. WS 流只要失败就用 REST tickers 降级。重连退避 15 秒、30 秒、之后 60 秒，一条连接稳定流式 30 秒后重新计数。
   订阅后 20 秒内没有任何 ticker、或之后连续 30 秒没有 ticker（只有保活不算）也算失败，失败信息会带上 OKX 的
   回答。保活用 OKX 的文本 `ping`/`pong`；1000/1001 正常关闭或 OKX 的 64008 重启通知会在一秒后重连，不算错误。
4. 解析后的 ticker 在线程中批量 upsert 到 `market_tickers`，不占用 worker 的事件循环：每次 REST 快照（约 700 条）
   一个事务，WS 约每秒一批（同一品种取最新）。此前逐条在事件循环里写库，会让 worker 所有循环停摆 9 秒到一分多钟。
5. 用户发起归纳时，Agent 从 PostgreSQL 读取最新异动。
   市场热度总结还会基于近期 ticker 快照计算 breadth：上涨数、下跌数、平均 UTC0
   涨跌幅、最强/最弱标的。
6. 用户询问具体已上线标的时，Agent 通过 `market_ticker` 精确读取一个
   `market_tickers.inst_id`。
7. 用户询问走势或 K 线研究时，Agent 通过 `market_candles` 按需从 OKX REST 获取近期 K 线；
   Sprint 10 不持久化历史 K 线。
8. 用户询问多标的强弱比较时，Agent 通过 `market_compare` 复用多个标的的 K 线摘要；
   Sprint 11 不单独持久化比较结果。
9. Sprint 48 增加 `market_intelligence`：只读、connector-neutral 的市场情报层，
   针对一个 SWAP 标的读取 OKX public funding rate 和 open interest，并合并
   `docs/knowledge/market-intelligence-curated.md` 的 deterministic curated context。

原始 ticker 用于短期运行，聚合摘要长期保留。
K 线在 Sprint 10 中只作为短生命周期研究输入。
市场情报不是交易信号；每条结果都带 `source`、`source_path`、`symbol`、
`as_of`、`freshness_seconds`、`metrics`、`missing_fields` 和有界 `sample`，
用于在报告里展示来源、时间和缺失字段，不补造不可用数据。
