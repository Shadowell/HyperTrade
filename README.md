# HyperTrade

[中文](README.zh-CN.md) | [English](README.en.md)

HyperTrade is a crypto trading agent for market research and execution. Current V1 covers observable Agent graph runs, provider routing including Codex, tool calling, RAG citations, audited Memory, OKX market research, paper trading, strategy experiments, strategy library memory, risk-gated live intents, OKX Testnet signed execution, and a BitPro MCP adapter for external data access, backtest artifacts, paper evidence snapshots, plus non-live strategy lifecycle workflows.

> Research output only. Nothing in this repository is investment advice.

## Quick Start

```bash
cp .env.example .env
uv run pytest -q
npm exec --yes pnpm@10 -- -C frontend install
npm exec --yes pnpm@10 -- -C frontend dev
uv run uvicorn hypertrade.main:app --app-dir backend/src --host 0.0.0.0 --port 3334
```

## Verification

```bash
./scripts/check.sh
```

This runs frontend install/lint/test/build, Python ruff, mypy, and pytest.

## CLI

Start the standalone terminal Agent:

```bash
uv run hypertrade
# short alias
uv run ht
```

Run one prompt locally:

```bash
uv run hypertrade ask "请做行情归纳"
```

Use the terminal harness against a running API:

```bash
uv run ht /login
uv run ht ask "请做行情归纳"
```

`/login` saves the remote API URL, username, and password to
`~/.hypertrade/client.env` with local-only file permissions. After that,
`uv run ht` defaults to the saved remote API unless `--local` is passed.

Force local mode even when `HYPERTRADE_API_URL` is set:

```bash
uv run hypertrade --local
```

In interactive chat, slash commands inspect harness state without starting a new Agent run.
`/help` explains every command, and `/tools` shows each Agent tool with its category,
approval gate, and purpose:
Enter `/` to display the command list, or press Tab after `/` or a partial command such
as `/m` to complete available slash commands and common subcommands.
Short incomplete prefixes such as `/st` or `/me` render a filtered candidate list with
descriptions instead of starting an Agent run or dumping the full help page.
In interactive chat, slash command and argument candidate lists are numbered;
enter a number to select the displayed alternative directly.
Run `/model` in interactive chat to choose the active provider from a numbered
list; when Codex is selected, its model is chosen from the configured
`CODEX_MODEL_OPTIONS` list. Scripted switches such as `/model codex` still work.
Free-form Agent prompts show a live `Thought` / `Thinking` status block in interactive
terminals while the planner or tools are still running.
Interactive terminals also render Markdown reports into readable headings, lists, and tables;
set `HYPERTRADE_RENDERER=plain` when raw Markdown is needed for scripts.
Rich terminal output hides run metadata and trace tables by default so routine answers show
only the core report; set `HYPERTRADE_TRACE=summary` for a compact trace or
`HYPERTRADE_TRACE=full` when a full audit trace is needed.
Streaming progress is compact by default (`Agent: running/completed`). Set
`HYPERTRADE_PROGRESS=full` to see every tool start/completion line. BitPro paper
monitor/equity/event reports prefer concise conclusions and core metrics; set
`HYPERTRADE_REPORT_SOURCE=tools` only when raw tool evidence tables are needed.
Broad prompts such as `看下目前市场的热度怎么样` return a market heat summary with
advancer/decliner breadth, average change, strongest/weakest symbols, and the
top movers; set `HYPERTRADE_REPORT_SOURCE=tools` to inspect raw ticker/candle
tables instead.

```text
/help
/status
/tools
/runs
/memory
/strategy
/strategy library momentum_breakout_v1
/research 研究BTC趋势突破
/backtest
/backtest latest
/rag risk
/memory search risk
/model deepseek
/model codex
/experiment 研究ETH趋势突破
/monitors
/monitor run mon_bitpro_paper_all
/alerts
/live execute loi_...
/evals
```

## Documentation Map

- `docs/README.md`: documentation index and current capability map.
- `docs/spec.md`: product scope, acceptance criteria, and boundaries.
- `docs/progress.md`: latest implementation/deployment state.
- `docs/architecture/19-hypertrade-architecture-diagram.md`: layered HyperTrade architecture diagram.
- `docs/architecture/`: module-level architecture notes.
- `docs/knowledge/tool-usage-guide.md`: operator guide for Agent tools and validation.
- `docs/runbooks/`: deployment, BitPro MCP, monitoring, smoke, backup, and incident procedures.
