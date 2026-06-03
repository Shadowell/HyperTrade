# Agent Acceptance Test Plan

## Purpose

This document defines how to test whether HyperTrade Agent behavior is reasonable across tool calling, RAG, Memory, market research, strategy research, and backtesting. The tests focus on observable behavior, not exact LLM wording.

> Research and learning project only. Nothing here is investment advice.

## Automated Test Entry Points

Run the focused Agent acceptance suite:

```bash
uv run pytest tests/test_agent_acceptance.py -q
```

Run the full project check:

```bash
./scripts/check.sh
```

## Automated Cases

| Case | Prompt shape | Expected tools | Output checks |
| --- | --- | --- | --- |
| Specific symbol行情 | `看下DOGE行情` | `market_ticker` | Report contains `## 单标的行情`, exact `DOGE-USDT-SWAP`, latest price, and disclaimer. |
| Trend + compare | `看下ETH走势，并和SOL比较哪个更强` | `market_candles`, `market_compare` | Report contains `## K线趋势特征`, `## 多标的强弱比较`, ranking, leader, and disclaimer. |
| RAG + Memory | `结合知识库和记忆，说下资金费率风险` | `rag_search`, `memory_search`, `memory_write` | Trace links RAG hit source path, writes audited memory id, and records tool inputs in `report_json`. |
| Strategy + backtest | `研究ETH趋势突破并回测` | `strategy_draft`, `backtest_run` | Trace contains `srch_*` research id, `bt_*` backtest id, completed status, metrics, and disclaimer. |

## Sprint 24-31 Additions

| Case | Entry point | Expected checks |
| --- | --- | --- |
| Agent graph trace | `hypertrade ask "看下ETH行情"` | Trace includes `graph.intent_classify`, `graph.plan_tools`, `graph.reflect`, and `graph.final_report`; business tools are still visible. |
| Provider switch | `/model deepseek`, `/model openrouter` | CLI/API switch session provider without returning secrets; missing keys show `missing`. |
| RAG citation search | `/rag 风控` | Hits show source path, title, chunk index, score, and preview. |
| Memory v2 | `/memory search 风控` | Results show tags/usage and retain source run/tool. |
| Risk refusal | Create Mainnet or oversized intent in tests | Intent becomes `risk_blocked` with structured violation. |
| Testnet execution | `/live execute loi_*` | Approved Testnet intent records redacted request and exchange response or auditable failure. |
| Strategy experiment | `/experiment 研究ETH趋势突破` | Creates `exp_*`, linked `srch_*`, linked `bt_*`, critique, next experiment, and disclaimer. |
| Eval suite | `/evals` | Deterministic eval status shows tool selection, RAG citation, memory, risk refusal, and Testnet safety cases. |

## Output Quality Rules

Every Agent report should:

- Be non-empty Markdown.
- Include `Research output only. Not investment advice.`
- Include structured sections when deterministic market tools return payloads.
- Preserve exact instrument ids when the user asks for a specific symbol.
- Keep tool calls visible through trace events.

Every Agent report should avoid:

- `保证收益`
- `稳赚`
- `建议买入`
- `建议卖出`
- `满仓`
- `all in`

## Server Smoke Cases

After deploying to `47.79.36.92`, run:

```bash
hypertrade ask "看下ETH行情"
hypertrade ask "看下ETH走势，并和SOL比较哪个更强"
printf "/price ETH\n/candles ETH --bar 1H --limit 50\n/compare ETH SOL --bar 4H --limit 100\n:q\n" | hypertrade
printf "/paper status\n/paper pause\n/paper resume\n:q\n" | hypertrade
printf "/research 研究BTC趋势突破\n/backtest --source bitpro --symbol BTC --bar 1H --limit 200\n:q\n" | hypertrade
printf "/research 研究ETH趋势突破\n/backtest --live --symbol ETH --bar 1H --limit 100\n:q\n" | hypertrade
printf "/model deepseek\n/rag 风控\n/memory search 风控\n/evals\n:q\n" | hypertrade
printf "/experiment 研究ETH趋势突破\n:q\n" | hypertrade
```

Expected server observations:

- CLI prints run id and tool progress lines.
- Free-form prompts print readable Agent statuses for run creation, planning, tool execution, tool completion, and final report generation.
- Free-form market prompts prefer structured CLI report sections such as `Agent Report`, `Ticker`, `Trend`, and `Relative strength` instead of raw Markdown when trace payloads are available.
- Rich terminal rendering can be forced with `HYPERTRADE_RENDERER=rich`; script-friendly plain text can be forced with `HYPERTRADE_RENDERER=plain`.
- Deterministic market shortcuts print exact ticker, K-line trend, and relative-strength blocks without starting an LLM-planned Agent run.
- Paper slash commands print the simulated session state and can pause/resume the paper runtime without touching live trading.
- BitPro archive backtests print data source `bitpro_sqlite_candles` when `BITPRO_SQLITE_PATH` is configured.
- Specific-symbol prompt includes exact instrument such as `ETH-USDT-SWAP`.
- Compare prompt includes relative-strength ranking.
- Backtest command prints data source `okx_rest_candles`, instrument, bar, candle count, return, and trade count.
- Graph status, RAG citations, Memory search, provider status, and eval status are visible from CLI.

## Notes

- Automated tests replay fake DeepSeek responses, so CI does not need provider keys.
- Automated tests do not call OKX. Live OKX behavior is covered by server smoke tests.
- The suite checks behavioral contracts rather than exact prose snapshots, so future model wording changes should not create noisy failures.
