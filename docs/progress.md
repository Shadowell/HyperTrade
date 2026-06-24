# Progress Log

## Current Baseline

- Branch: `main`
- Harness status: active
- Last verified state: Sprint 66 README architecture/onboarding refresh verified
  locally with `./scripts/check.sh` (`pytest` 233 passed).

## Active Contract

- `docs/contracts/sprint-66-readme-architecture-refresh.md`

## Current In-Progress Work

- Sprint 66 README architecture/onboarding refresh is implemented and locally
  verified. The remaining handoff step is the standard main-branch push,
  deployment watch, and production health verification.
- Sprint 65 live strategy performance routing was committed, pushed, deployed,
  and production-smoked separately from the README refresh. The remaining
  README/Sprint 66 files in the worktree are unrelated to this fix.

## Latest Completed Work

- Added Sprint 66 README architecture/onboarding refresh: the root README now
  embeds `docs/assets/hypertrade-architecture.svg`, explains the
  HyperTrade/BitPro boundary, summarizes V1 capabilities, documents core
  workflows, names the Codex model allowlist behavior, and adds safety,
  documentation-map, and repository-layout sections. Verification passed with
  full `./scripts/check.sh` (`pytest` 233 passed).
- Added Sprint 65 live strategy performance routing: prompts such as
  `看下实盘收益最高的策略` now route directly to the read-only
  `bitpro_live_strategy_performance` tool instead of falling back to OKX market
  heat. The BitPro adapter preflights capability/health, reads
  `/live/strategies`, ranks returned rows by the page metric `return_pct`,
  reports `total_pnl` when present, and renders a `BitPro 实盘策略收益` section.
  Verification passed with focused Agent/planner/adapter/report/registry tests
  and full `./scripts/check.sh` (`pytest` 233 passed). Deployment run
  `28083803949` completed successfully for SHA `d3173a1`, public
  `GET http://47.79.36.92:3333/api/health` returned `ok`, and remote CLI smoke
  run `run_233a0cf96acb45a9a12f` answered `看下实盘收益最高的策略` with
  `BitPro 实盘策略收益` plus `bitpro.live_strategy_performance` trace.
- Added Sprint 64 Codex GPT-5.5 option: default `CODEX_MODEL_OPTIONS` now
  includes `gpt-5.5` between `gpt-5.4` and `gpt-5.4-mini`, while `CODEX_MODEL`
  remains `gpt-5.4`. This explains why 5.5 was missing before: the CLI model
  picker is backed by a configured allowlist rather than live model discovery.
  Verification passed with focused provider tests and full `./scripts/check.sh`
  (`pytest` 229 passed).
- Added Sprint 63 CLI selectable candidates: slash command and slash argument
  candidate lists now render numbered alternatives, interactive chat prompts
  for a candidate number, and selected candidates dispatch through the same
  deterministic slash-command handlers. This includes partial commands such as
  `/st` and argument candidates such as `/model c`, which continues into the
  Codex model picker after selecting `codex`. Verification passed with focused
  CLI tests and full `./scripts/check.sh` (`pytest` 228 passed).
- Added Sprint 62 live order-history routing: live/real-account order-history
  prompts such as `我的实盘最近的一笔订单是什么` now route directly to the
  read-only `bitpro_live_order_history` tool instead of market fallback. The
  BitPro adapter preflights capability/health, reads `/trading/orders/history`,
  records source tool calls, and planner guidance forbids `market_summary` for
  live account order-history questions. Verification passed with focused
  planner/adapter/Agent tests and full `./scripts/check.sh` (`pytest` 225
  passed).
- Added Sprint 61 CLI Codex model picker: interactive `/model` now renders a
  numbered provider list and, when Codex is selected, a numbered Codex model
  list sourced from `CODEX_MODEL_OPTIONS`. Local and remote sessions carry the
  selected model into `AgentKernel` chat/planner calls, API provider selection
  validates optional model overrides, and provider status exposes
  `model_options` without exposing Codex tokens. Verification passed with
  focused provider/API/CLI tests and full `./scripts/check.sh` (`pytest` 225
  passed).
- Added Sprint 60 monitor scheduler worker: default monitor definitions now use
  conservative interval schedules, `MonitorService.run_due_monitors()` runs due
  monitors while skipping manual/disabled/not-due definitions, and
  `hypertrade.worker` has a `MONITOR_SCHEDULER_ENABLED`-gated scheduler loop
  that persists monitor runs and alert events without calling paper/live write
  tools. Verification passed with focused monitor/worker tests and full
  `./scripts/check.sh` (`pytest` 225 passed).
- Added Sprint 59 CLI argument candidate display fix: slash-command candidate
  rendering now also understands argument completions from
  `SLASH_ARGUMENT_COMPLETIONS`, so inputs such as `/model c` show `codex`
  instead of displaying no matches or dispatching `c` as a fake provider. The
  readline display hook and Enter-on-partial-argument path are covered by
  focused CLI regression tests. Verification passed with focused candidate
  tests and full `./scripts/check.sh` (`pytest` 213 passed).
- Added Sprint 58 Codex provider runtime: HyperTrade now exposes `codex` as a
  selectable chat/planner provider, accepts Hermes-style `openai-codex` as an
  alias, reads server-only `CODEX_API_KEY` or `CODEX_AUTH_JSON` access tokens
  without exposing secrets in provider status, and routes planner calls through
  the Codex Responses API while HyperTrade still owns ToolRegistry execution,
  risk policy, trace, RAG, and Memory. Verification passed with focused
  ruff/mypy/provider/API/CLI tests and full `./scripts/check.sh` (`pytest` 211
  passed).
- Added Sprint 57 architecture diagram: `docs/assets/hypertrade-architecture.svg`
  provides a poster-style layered map for client access, data inputs, Agent
  gateway, HyperTrade engine, execution/output, multi-Agent workflow,
  infrastructure, closed-loop workflow, and safety/compliance. The companion
  `docs/architecture/19-hypertrade-architecture-diagram.md` documents layer
  responsibilities and the HyperTrade/BitPro boundary.
- Completed Agent 52 / Sprint 52 frontend operator console polish:
  `/harness` keeps BitPro result ids labeled as `bitpro_result`, reads monitor
  alerts from the actual `/api/alerts` endpoint, and documents the Strategy
  Library, structured report block, evidence drilldown, alert empty-state, and
  read-only approval/risk surfaces. Verification passed with frontend
  lint/test/build, API smoke for `/api/strategy/library`, `/api/alerts`, and
  `/api/health`, plus full `./scripts/check.sh` (`pytest` 207 passed).
- Added Sprint 54 connector framework: trusted connector protocol/dataclasses,
  `ConnectorRegistry`, deterministic `FixtureConnector`, and `BitProConnector`
  compatibility wrapper over the existing BitPro MCP adapter. Redacted
  connector capabilities are exposed through `GET /api/connectors/capabilities`,
  `/api/harness/overview.connectors`, CLI `/connectors`, and ToolRegistry
  `connector_origin` metadata for BitPro-backed tools. Focused verification:
  `uv run pytest tests/test_connector_framework.py tests/test_tool_registry.py
  -q`, `uv run pytest tests/test_cli.py -q`,
  `uv run pytest tests/test_api.py -q`, contract verification
  `uv run pytest tests/test_bitpro_mcp_adapter.py tests/test_tool_registry.py
  -q`, `uv run pytest tests/test_agent_acceptance.py -q`, and full
  `./scripts/check.sh` (`pytest` 207 passed).
- Added Agent 53 / Sprint 53 evaluation suite hardening: `/evals` now exposes
  deterministic guardrail cases for strategy-library source use, BitPro
  page-parity result metrics, missing artifact disclosure, paper-monitor
  read-only behavior, and compact/default report rendering. The eval contract
  includes required/forbidden tools, report fragments, source ids, and
  missing-data expectations; fixture helpers cover source-bound tool outputs and
  strategy-memory evidence.
- Verification: `uv run pytest tests/test_agent_acceptance.py -q` -> 16
  passed; `uv run pytest tests/test_agent_eval_suite.py -q` -> 5 passed;
  `uv run pytest tests/test_api.py tests/test_cli.py -q` -> 69 passed;
  `./scripts/check.sh` -> frontend install/lint/test/build passed, ruff and
  mypy passed, pytest 207 passed.
- Added the Sprint 51 monitoring and alerts runbook and docs links for
  `/monitors`, `/monitor run <monitor_id>`, `/alerts`, and the matching monitor
  API. The runbook records the read-only boundary, default monitors,
  threshold/alert payloads, and manual smoke path for BitPro paper monitoring,
  strategy-library freshness, and connector health.
- Added Sprint 56 market heat summaries: broad all-market heat/sentiment/breadth
  prompts now route to `market_summary`, compute OKX SWAP breadth metrics
  (`advancers`, `decliners`, average UTC0 change, strongest/weakest symbols),
  and render a conclusion before raw ticker details. CLI market detail runs now
  default to final-summary-first output while `HYPERTRADE_REPORT_SOURCE=tools`
  keeps raw ticker/candle tables available for debugging.
- Added Sprint 55 CLI slash-command candidate filtering: incomplete prefixes
  such as `/st` or `/me` now render filtered command candidates with the same
  descriptions as `/help`, and real TTY readline completion registers a display
  hook for described Tab candidates.
- Added Sprint 49 risk governance policy: `RiskGovernancePolicy` evaluates
  registered Agent tools before execution, classifies read/research-write/
  paper-write/testnet-write/live-diagnostic scopes, denies write-like external
  actions missing `idempotency_key`, records `policy_decision` in graph trace,
  and renders denied BitPro lifecycle writes in a `风控治理` report section
  without calling the external adapter.
- Added Sprint 48 multi-source market intelligence: connector-neutral result
  schema/service layer, OKX funding/open-interest client reads, curated context
  fixture, Agent planner schema, kernel executor branch, ToolRegistry entry, and
  compact report rendering. Verification is covered by
  `tests/test_market_intelligence.py`, planner/registry tests, and the combined
  `./scripts/check.sh` pass with 203 Python tests.
- Added Sprint 47 evidence-driven strategy loop: `StrategyIterationService`
  reads `StrategyLibraryService` before iteration, produces bounded
  source-backed variant plans, and lets API/CLI experiment flows compare a new
  winner against prior best evidence without claiming improvement when metrics
  are missing or worse.
- Added Sprint 46 strategy evidence schema: new `strategy_knowledge` Memory
  writes now store versioned `StrategyEvidence` JSON payloads in
  `MemoryItem.content`, preserving exact Memory dedupe/search behavior while
  letting `StrategyLibraryService` prefer structured evidence and fall back to
  legacy text cards. The strategy library now preserves schema version,
  optional BitPro result ids, source data, research-only boundaries, gate
  results, failure reasons, and safe missing-field defaults; focused Sprint 46
  verification passed with `uv run pytest tests/test_strategy_library.py
  tests/test_strategy_backtest_api.py -q` and `uv run pytest tests/test_cli.py
  tests/test_agent_planner.py -q`.
- Added the post-Sprint-44 capability roadmap for parallel Agent development:
  `docs/architecture/18-hypertrade-capability-roadmap.md` defines the target
  capability map and dependencies, and Sprint contracts 45-54 split Agent
  runtime reliability, strategy evidence schema, evidence-driven strategy loops,
  multi-source market intelligence, risk governance, report provenance,
  monitoring/alerts, frontend operator console, evals, and connector framework
  into independent handoff packages.
- Added copy-ready prompts for parallel development agents in
  `docs/agent-prompts/parallel-sprint-prompts.md`, covering Sprint 45-54 plus a
  coordination-only lead Agent prompt.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 161 tests.
- Aligned the HyperTrade BitPro adapter with BitPro MCP Agent Token management: local `bitpro_capabilities` and `/api/harness/overview` now expose `remote_mcp`, `agent_auth`, token-management routes, R/W/L/T scope classes, live-diagnostic grouping, and idempotency-required tools without exposing token plaintext; `/harness` also shows a compact BitPro MCP access status panel for Token source/header/scope checks.
- Tightened CLI/Agent paper-report output: default stream progress now folds to `Agent: running/completed`, Rich and plain renderers prefer concise final BitPro paper reports, old noisy paper Markdown with strategy inventories or equity-point samples is folded into a compact paper summary, and `HYPERTRADE_PROGRESS=full` / `HYPERTRADE_REPORT_SOURCE=tools` keep debug/audit detail available.
- Shortened server-side BitPro paper final reports: paper dashboard/events/equity/snapshot sections now include the planner conclusion plus core metrics, alerts, data gaps, and latest error only, without raw strategy inventory rows, equity-point samples, ordinary event rows, contract/tool-order fields, or citation sections.
- Made default CLI run rendering report-focused and compact: run headers, status/tool trace tables, folded-trace notices, and wrapper `Agent Report` panels are hidden unless `HYPERTRADE_TRACE=summary/full` is set; Markdown report spacing is compacted and horizontal separators are removed.
- Added Sprint 44 strategy library memory: audited `strategy_knowledge` Memory cards now aggregate into strategy-level summaries with evidence counts, pass/fail counts, best/latest evidence, variants, failure reasons, next experiments, and source memory ids. The capability is exposed through `GET /api/strategy/library`, CLI `/strategy library [query]`, Agent planner tool `strategy_library_search`, and ToolRegistry entry `strategy.library_search`; new strategy memory cards include variant count, gate results, and failure reasons.
- Cleaned default CLI/Rich report rendering so low-value citation sections, poor terminal emoji/keycap glyphs, and noisy per-tool progress lines are hidden by default while `HYPERTRADE_REPORT_SOURCE=tools` and `HYPERTRADE_PROGRESS=full` keep audit/detail paths available.
- `uv run pytest tests/test_strategy_library.py tests/test_strategy_backtest_api.py tests/test_agent_planner.py tests/test_market_candles_tool.py tests/test_cli.py tests/test_tool_registry.py -q` -> 84 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 155 tests.
- Added CLI slash-command discovery: entering `/` now displays the command list without an unknown-command warning, and real TTY readline sessions register Tab completion for slash commands plus common subcommands such as `/model`, `/memory`, `/paper`, `/live`, and `/backtest`.
- Added Sprint 43 BitPro paper monitor snapshots: Agent tool `bitpro_paper_monitor_snapshot` now captures dashboard, event summary, and equity summary through read-only BitPro MCP/API tools, persists normalized metrics and nested BitPro tool calls, compares with the previous snapshot for the same scope, and renders PnL/equity/drawdown/error drift in Agent/CLI reports without triggering paper or live write tools.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 143 tests.
- Added Sprint 42 BitPro paper evidence layer: Agent tools `bitpro_paper_events` and `bitpro_paper_equity_curve` now preflight through BitPro MCP, read bounded event/error and equity/drawdown evidence, record nested trace calls, and render source-bound Agent/CLI paper monitoring evidence without synthesizing missing rows.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 137 tests.
- Added Sprint 41 documentation refresh: root READMEs, `docs/README.md`, knowledge guides, architecture notes, deployment docs, testing plan, and smoke runbook now describe the current production Agent surface, BitPro MCP boundaries, page-focused BitPro reports, strategy knowledge memory, and operator validation paths.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 131 tests.
- Improved BitPro backtest detail CLI formatting: plain and Rich output now group core metrics and artifact samples with Chinese labels, and Rich metric values use semantic colors while respecting `NO_COLOR`.
- Kept default BitPro backtest Agent reports page-focused: completed backtest result/detail sections no longer include MCP contract/tool-order debug fields, lifecycle polling summaries, or RAG citation lists unless operators explicitly inspect trace/debug evidence.
- Added Sprint 40 strategy knowledge memory sedimentation: completed local strategy experiments now write one audited `strategy_knowledge` Memory item with experiment/research/backtest ids, winning variant, parameters, return, drawdown, trade count, evidence gates, data selection, and next-experiment guidance. The item is tagged for strategy, experiment, evidence, strategy key, and winning variant searches so future Agent runs can retrieve prior evidence through existing Memory API/CLI/UI surfaces.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 131 tests.
- Updated CLI structured BitPro rendering so `bitpro_backtest_get_result` appears as a dedicated backtest detail block in both Rich and plain output, and mixed ranking/detail runs no longer hide the page-parity result details behind the ranking table.
- Suppressed BitPro lifecycle polling logs when a report already contains BitPro backtest result/detail evidence, so strategy backtest prompts stay focused on page-parity metrics and artifact availability instead of appending tool lifecycle rows.
- Added semantic CLI colors for interactive TTY output: slash-command help now colors commands/descriptions, `/tools` colors tool names/categories/approval markers/descriptions, Agent streaming status colors progress/tool/success/error lines, remote API errors use error color, and non-TTY or `NO_COLOR=1` output remains plain for scripts.
- Fixed remote CLI streaming for long BitPro backtests: `hypertrade`/`ht` now keeps SSE reads open while preserving connect/write/pool timeouts, so a quiet upstream BitPro backtest does not bounce the local chat session with a misleading deploy/restart connection error. Remote connection error text now states that the run may still be continuing and points operators to retry or inspect `/runs`.
- Added readline-backed interactive CLI command history: real TTY `hypertrade` chat sessions now load/write `~/.hypertrade/history`, add non-empty prompts and slash commands to history, skip consecutive duplicates, and keep non-TTY/script behavior unchanged so up-arrow recalls prior requests instead of printing escape sequences.
- Fixed mixed-tool CLI rendering for BitPro paper monitoring: structured Agent output now keeps the `bitpro_paper_dashboard` monitor block when market ticker tools appear in the same run, instead of rendering only ticker sections and hiding the BitPro report evidence.
- Fixed BitPro backtest job result reporting: Agent-triggered `bitpro_backtest_start_job` now waits for the BitPro-owned job to reach a terminal state, normalizes the completed `job.result`, links it back to the saved BitPro result row when available, and renders a concise `BitPro 回测结果` section with page-parity metrics instead of a lifecycle polling log.
- Added a deterministic BitPro paper monitor summary: unfiltered `bitpro_paper_dashboard` now returns `monitor_summary` with current dashboard equity/PnL/Sharpe/drawdown, running strategy inventory coverage, data gaps, alerts, and read-only recommended actions. Agent reports render a `监控结论` block and explicitly avoid inferring per-strategy PnL/drawdown when BitPro's running-strategy inventory does not include those metrics.
- Added a read-only BitPro backtest detail evidence path: Agent tool `bitpro_backtest_get_result` now preflights `bitpro_capabilities`/`bitpro_health`, reads `backtest_get_result`, normalizes metrics plus bounded equity curve/trades/orders/fills/drawdown artifact samples, records nested `bitpro.backtest_get_result` trace evidence, and renders a dedicated `BitPro 回测详情` report section without synthesizing missing artifacts or appending model-generated evidence prose.
- Clarified BitPro live-state reporting in HyperTrade: `live_trading_enabled` is now explicitly labeled as the HyperTrade MCP live write/order gate, `/harness` exposes the same scope/note, and the planner/report renderer are instructed not to infer BitPro paper/live runtime mode from that flag. Runtime mode should come from BitPro dashboard/live read tools instead; paper/dry-run dashboard evidence must not be summarized as BitPro globally having live trading disabled.
- Upgraded the local strategy experiment workflow into a small evidence loop: `/experiment <prompt>` now runs baseline, fast, and conservative `momentum_breakout_v1` variants through normal Backtrader `BacktestRun` persistence, stores `variants`, `winner`, and `evidence_gates` in `strategy_experiments.report_json`, records the winning backtest id on the experiment row, and renders a candidate comparison table plus winning rationale in the report.
- Removed model-generated emoji/icons from CLI Markdown report rendering: Rich and plain Agent reports now strip poor terminal emoji glyphs such as chart/check/warning icons before display, while keeping the report headings, list structure, and text readable.
- Improved CLI readability for BitPro backtest result reports: `bitpro_backtest_list_results` trace payloads now render as a Rich summary panel plus compact ranking table with rounded total return, drawdown, Sharpe, win rate, trade count, and period fields instead of falling back to long raw Markdown bullets. Plain structured output also uses concise ranking rows while preserving the `total_return_pct` source-of-truth metric.
- Updated the high-visibility product positioning copy to emphasize HyperTrade as "A crypto trading agent for market research and execution" instead of a platform/system/harness; README, product spec, Chinese README, and CLI welcome banner now use the trading-agent framing.
- Added first-class local remote-login configuration to the CLI: `hypertrade /login` / `ht /login` now prompts for API URL, username, and password, writes `~/.hypertrade/client.env` with `0600` permissions, and makes later `ht` / `ht ask ...` commands default to the saved remote API unless `--local` is passed. Explicit `HYPERTRADE_*` environment variables still override saved config for automation.
- Simplified `/harness` into a core operator workbench: the page now keeps Agent run creation, report reading, tool trace, Memory search/detail, RAG search, OKX top movers, recent runs, and core telemetry. Advanced controls for BitPro MCP contract display, provider switching, paper lifecycle, live approval/execution, strategy lab/backtests, evals, Feishu send, and Memory disable were removed from the primary UI; the underlying privileged API/CLI paths remain guarded where they still exist.
- Removed the `/harness` login wall for workbench observability: the frontend now loads live overview/Memory data directly, shows real run history and trace instead of preview zeros, and no longer renders the sidebar login form. Public workbench/research endpoints cover overview, Agent runs, market reads, RAG, Memory list, strategy research/experiments, and backtests; privileged mutations such as provider selection, paper controls, live approval/execution, Memory disable, and Feishu send remain admin-authenticated.
- Added a BitPro backtest result read path for page-parity questions: `bitpro_backtest_list_results` now preflights `bitpro_capabilities`/`bitpro_health`, reads `backtest_list_results` with `offset`/`limit` pagination, filters actual `total_return_pct`, enriches strategy names through `strategy_get`, renders a dedicated `BitPro 回测结果` report section, and teaches the planner not to substitute annualized return or inferred values for total backtest return.
- Changed the production host CLI wrapper so `/usr/local/bin/hypertrade` starts a short-lived remote client container that connects to `http://api:3334` instead of `docker compose exec` into the long-running `hypertrade-api` service. Deployment can still interrupt an in-flight API request, but it no longer kills the operator's terminal session; the CLI now prints a retryable remote API message on HTTP disconnects and returns to the chat loop.
- Folded low-signal Rich CLI trace output by default: graph runtime nodes, BitPro capability/health preflight rows, and nested BitPro subcalls are now summarized instead of printed as a long table; business-level tools remain visible with call counts, and `HYPERTRADE_TRACE=full` restores full trace output for audits through both local CLI and the server host wrapper.
- Fixed BitPro paper/simulation inventory reporting: production `paper_dashboard` was verified to expose only the current dashboard strategy (`strategy_id=105`), while `strategy_search(status=running)` exposed 12 running strategies. HyperTrade now augments unfiltered `bitpro_paper_dashboard` with safe-paginated running strategy inventory, adds `paper_scope` metadata, teaches the planner not to infer a single strategy from the current dashboard view, and renders a dedicated `BitPro 模拟盘状态` report section.
- Implemented the BitPro MCP adapter in HyperTrade: server-side settings for `BITPRO_MCP_API_BASE`/token/header, `BitProMcpClient`, `BitProToolAdapter`, Agent tool schemas and executor wiring, nested trace events for `bitpro_capabilities` -> `bitpro_health` -> read/non-live lifecycle tool calls, admin API endpoints for health/K-lines/paper dashboard/live positions, `/harness` BitPro adapter status, and `candle_source=bitpro_mcp` backtest data access.
- Added Rich Markdown fallback rendering for CLI reports: when structured JSON/trace sections are unavailable, interactive/Rich output now formats Markdown headings, lists, and tables instead of showing raw `###` and pipe-table source; `HYPERTRADE_RENDERER=plain` keeps script-friendly raw Markdown.
- Added interactive CLI Agent thinking feedback: free-form prompts now show a live `Thought` / `Thinking` animation in TTY sessions while waiting for planner/tool/final-report events, while non-TTY script output keeps stable `Agent status:` lines.
- Added CLI command/tool descriptions: `/help` now renders every slash command with a purpose statement, and `/tools` prints each registered Agent tool with category, approval marker, and registry description.
- Added BitPro strategy lifecycle Agent tools: strategy search/generation/creation, BitPro-owned backtest job start/status reads, and paper/simulation configure/start/pause/resume/stop. Live mutation tools remain blocked by the BitPro adapter.
- Added HyperTrade-side support for the forthcoming BitPro `strategy_update` MCP tool: API-path mapping to `PUT /strategies/{strategy_id}`, `BitProToolAdapter.strategy_update`, Agent planner schema, AgentKernel dispatch, nested trace name `bitpro.strategy_update`, `/harness` tool listing, and docs. This lets HyperTrade rename or patch BitPro strategies through MCP once BitPro exposes the tool, without direct DB writes.
- Validated the production BitPro MCP strategy R&D loop on the server using MCP tools only. `bitpro_capabilities` returned `bitpro-mcp-v1` with live trading disabled, `bitpro_health` returned healthy, and `market_klines` confirmed 720 real ETH/USDT:USDT 1h candles from `2026-05-10T14:00:00Z` to `2026-06-09T13:00:00Z`.
- Created DB-backed BaseStrategy strategy `#293` named `[永续][1h][趋势突破] ETH/USDT · Agent EMA ATR 回撤 · paper-v1 20260609134540` through `strategy_validate_code` and `strategy_create(script_content=...)`; no BitPro Python strategy files were edited and no BitPro restart was required.
- Started BitPro-owned backtest job `a292d098-0657-411d-9fff-3c82b9b384d8`; result `#196` completed for `2026-05-10` to `2026-06-09` with `4.0441%` total return, `1.4438%` max drawdown, `11` trades, `0.8029` Sharpe, `63.64%` win rate, and final capital `10404.4128`.
- Because the explicit gate passed (trade count >= 1, return > 0, absolute max drawdown <= 15%), configured and started paper dry-run for strategy `#293`. Live mutation tools were not called.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 86 tests for the BitPro strategy lifecycle slice.
- Redesigned the `/harness` operator UI toward a Chinese-first production console: sidebar, header, run monitor, tool trace, Memory/RAG, paper runtime, live approval, strategy lab, and status labels now use consistent Chinese technical copy while preserving protocol/tool names. Added a visible BitPro MCP access panel that documents the required `bitpro_capabilities` -> `bitpro_health` -> read-tool selection flow, and added `docs/runbooks/bitpro-mcp-data-access.md` for server-side MCP data access.
- Fixed the `/harness` sidebar section navigation so clicking `行情摘要`, `Memory`, or `RAG` updates the active sidebar item instead of leaving `Harness` permanently highlighted. Added a frontend regression test for the clicked section state and browser-verified the local page with Playwright.
- Reduced repetitive investment-advice disclaimer output for routine Agent/CLI usage: the welcome banner, deterministic market shortcuts, structured market reports, and planner system prompt no longer force a fixed disclaimer on every ordinary market/RAG/Memory response. Strategy, backtest, Testnet, live-order, and recommendation-like prompts still retain the research/risk boundary. Updated acceptance tests, `docs/spec.md`, `docs/contracts/sprint-32-production-agent-bitpro-tools.md`, `docs/testing/agent-acceptance-test-plan.md`, and `docs/knowledge/tool-usage-guide.md`.
- Applied `codex-project-template` development harness.
- Added FastAPI backend, AgentKernel, ToolRegistry, RAG, Memory, OKX market parser, worker loops, Alembic migration.
- Added React/Vite `/harness` and market summary frontend surface.
- Added Docker Compose, Nginx config, self-hosted GitHub Actions deployment.
- Added `/api/harness/overview` and wired `/harness` to live Provider, Tool, market, Agent run, RAG, Memory, and trace state.
- Added configurable `COOKIE_SECURE` so the current HTTP `3333` deployment can keep admin sessions, while HTTPS deployments can opt in to secure cookies.
- Added Sprint 02 automatic paper trading runtime with paper sessions, deterministic signals, simulated fills/positions, pause/resume API, worker loop, and `/harness` Paper Runtime panel.
- Added Sprint 03 strategy research and Backtrader backtest workflow with persisted research records, backtest runs, Markdown/JSON reports, API endpoints, and `/harness` Strategy Lab panel.
- Added Sprint 04 CLI conversation harness with `hypertrade ask` and `hypertrade chat` over the same FastAPI Agent runtime.
- Added Sprint 05 standalone hybrid CLI runtime so bare `hypertrade` starts an Agent terminal, `--local` forces local AgentKernel mode, and `--remote` connects to a deployed API.
- Added Sprint 06 CLI slash commands for `/help`, `/status`, `/model`, `/providers`, `/tools`, `/runs`, `/memory`, `/strategy`, and `/backtests` in local and remote interactive chat.
- Added Sprint 07 CLI workflow shortcuts `/research <prompt>` and `/backtest` to trigger strategy research and Backtrader backtests without a full Agent run.

- Added Sprint 08 LLM-driven agent planner: `DeepSeekClient`, `AgentPlanner` multi-turn tool-calling loop, and updated `AgentKernel` to use real DeepSeek function calling when `DEEPSEEK_API_KEY` is configured, with hardcoded fallback when not.
- Fixed DeepSeek thinking-mode compatibility by preserving `reasoning_content` across tool-call turns.
- Added Sprint 09 exact market ticker path: `market_ticker` planner tool, `market.ticker` registry entry, exact `MarketRepository.get_ticker()`, and symbol normalization for any listed OKX USDT SWAP symbol such as ETH, SOL, DOGE, or PEPE.
- Added stable planner report rendering for successful `market_ticker` calls so CLI/API answers always include exact price, UTC0 change, 24h volume, source, and timestamp.
- Added Sprint 10 market candles research path locally: OKX candle parsing, REST candle fetcher, deterministic trend feature extraction, `market_candles` planner tool, `market.candles` registry entry, AgentKernel execution, and stable K-line trend report block.
- Added Sprint 11 market relative-strength compare locally: `market_compare` planner tool, `market.compare` registry entry, deterministic strength scoring, ranking payload, and stable multi-symbol comparison report block.
- Added Sprint 12 CLI/API streaming locally: AgentKernel progress event emission, `POST /api/agent/runs/stream` SSE endpoint, remote SSE parsing, local streaming rendering, and CLI progress lines for run/tool events.
- Added Sprint 13 live candle backtest path locally: BacktestService can fetch OKX candles, convert them into Strategy SDK candles, accept API live-candle options, and pass `/backtest --live --symbol ETH --bar 1H --limit 100` from CLI.
- Added Sprint 14 Agent acceptance tests locally: deterministic replay tests now cover exact-symbol ticker output, K-line trend plus relative-strength comparison, RAG + Memory auditability, strategy research + backtest chaining, and report quality guardrails.
- Added `docs/testing/agent-acceptance-test-plan.md` with automated cases, server smoke commands, expected output checks, and forbidden advice phrases.
- Added Sprint 15 CLI market shortcuts locally: `/price`, `/candles`, and `/compare` call deterministic market payloads without waiting for LLM planning.
- Improved CLI Agent streaming status text so free-form runs show run creation, planning, tool execution, tool completion, and final report generation.
- Added Sprint 16 structured CLI report rendering locally: market-summary `report_json` and market tool trace outputs now render as structured CLI sections before falling back to Markdown.
- Added Sprint 17 Rich CLI rendering locally: structured market reports can render as terminal panels/tables when `HYPERTRADE_RENDERER=rich` or when running on a TTY, while `HYPERTRADE_RENDERER=plain` keeps script-friendly output.
- Updated the host CLI wrapper to pass safe display environment variables (`HYPERTRADE_RENDERER`, `NO_COLOR`) into the API container.
- Added Sprint 18 paper CLI controls locally: `/paper status`, `/paper pause`, and `/paper resume` call the existing paper runtime without starting an Agent run.
- Added Sprint 19 BitPro archived K-line backtest source locally: `BITPRO_SQLITE_PATH` can point to a BitPro SQLite DB, `/backtest --source bitpro --symbol ETH --bar 1H --limit 500` routes archived K-lines into Backtrader, and Compose mounts `${BITPRO_HOST_DATA_DIR:-/opt/bitpro/data}` read-only at `/bitpro-data`.
- Added Sprint 20 paper lifecycle controls locally: API and CLI now support `/paper close [symbol]` and `/paper reset`, close positions with realized PnL/events/fills, and reset by creating a new auditable running session.
- Added Sprint 21 live/testnet order approval gate locally: `live_order_intents` schema/service/API/CLI, Agent planner `live_order_intent` tool, and approve/reject status transitions without exchange execution.
- Added Sprint 22 frontend harness parity locally: `/harness` now includes Agent streaming status, market ticker/candle/compare shortcuts, paper close/reset controls, and Live Approval intent create/approve/reject UI.
- Added Sprint 23 frontend UX locally: styled Markdown report reader with raw toggle, Memory Manager with inspect/disable, and full backtest parameter form for strategy/source/symbol/bar/limit/cash.
- Added Sprint 24 Agent graph runtime locally: graph node trace events, `run_state_json`, streaming graph status, and deterministic fallback path.
- Added Sprint 25 Provider Router locally: `ChatProvider` protocol, OpenAI-compatible adapter, provider selection API, CLI `/model <provider>`, and frontend provider switcher.
- Added Sprint 26 RAG v2 locally: citation-ready RAG hits, deterministic vector fallback, `/api/rag/search`, CLI `/rag`, frontend RAG search, and Agent citation block support.
- Added Sprint 27 Memory v2 locally: importance/tags/confidence/usage fields, exact dedupe, search API, CLI `/memory search` and `/memory disable`, and frontend Memory search/tag display.
- Added Sprint 28 RiskEngine locally: Mainnet execution block, SWAP-only checks, max notional/open-intent checks, risk status persistence, and frontend/CLI risk display.
- Added Sprint 29 OKX Testnet signed execution locally: signed REST client, execute endpoint, CLI `/live execute`, redacted execution audit, and frontend execute button for approved intents.
- Added Sprint 30 strategy experiment workflow locally: hypothesis/data/backtest/critique/revision/report graph, `strategy_experiments`, API/CLI/frontend surfaces.
- Added Sprint 31 observability/evals/runbooks locally: deterministic eval suite, `/api/evals/status`, CLI `/evals`, frontend eval panel, and operations runbooks.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 72 tests.
- Implementation commit `4730898` pushed to `origin/main`; GitHub Actions run `26862283002` completed successfully and recorded deployed SHA `4730898c0b5bf9ce7778da230afb1930e427b910`.
- Server smoke passed for Sprints 24-31: server-local API `GET 127.0.0.1:3334/api/health` and Nginx `GET 127.0.0.1:3333/api/health` returned OK.
- Server authenticated `/api/harness/overview` smoke returned default provider `deepseek` with key status `configured`, `359` tickers, `12` tools, `4` RAG chunks, `17` active memory items, `33` Agent runs, `110` trace events, `0` pending live intents, and eval suite `passed` with `5` cases.
- Server CLI smoke passed through host `hypertrade --remote http://127.0.0.1:3334`: `/status`, `/model`, `/evals`, `/rag 风控`, and `/memory search 风控` all returned stable output.
- Server Agent graph smoke passed with `hypertrade --remote http://127.0.0.1:3334 ask "看下ETH行情"`: run `run_387de54f5531475f8d02` completed with graph trace events for `intent_classify`, `plan_tools`, `approval_check`, `execute_tool`, `reflect`, and `final_report`, plus market ticker/candle tool calls.
- Reframed Sprint 32 toward production-grade Agent operation: project copy, source comments, and `docs/knowledge/tool-usage-guide.md` now emphasize stability, auditability, operator workflows, and BitPro API tool-surface requirements.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `3a83b18`; frontend build produced `index-BLcqGC9-.js` and `index-Dty7kLGl.css`.
- Server smoke passed: API and Nginx health OK; authenticated overview returned `359` tickers, `17` active memory items, `0` pending live order intents; authenticated `/api/memory` returned `17` items.
- `npm exec --yes pnpm@10 -- -C frontend lint`, `test`, and `build` -> passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `a35e374`; server-local `GET 127.0.0.1:3334/api/health` and Nginx `GET 127.0.0.1:3333/api/health` returned OK.
- Server authenticated `/api/harness/overview` smoke returned `359` tickers, `0` pending live order intents, `1` recent live order intent, and paper session `running`.
- `uv run pytest tests/test_paper_service.py tests/test_api.py tests/test_cli.py -q` -> 27 passed.
- `uv run pytest tests/test_live_order_intents.py tests/test_api.py tests/test_cli.py -q` -> 23 passed.
- `uv run ruff check backend tests`, `uv run mypy backend/src` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 67 tests.
- Server deployed SHA `9f02367`; Alembic migrated `0003_strategy_backtest -> 0004_live_order_intents`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server host CLI smoke passed: `/paper status` rendered the running paper session, `/live intent ETH buy 0.01 --reason deploy smoke` created pending testnet intent `loi_10c5e2b8e34f469cb5e7`, and `/live reject loi_10c5e2b8e34f469cb5e7 --reason deploy smoke cleanup` moved it to `rejected`.
- Sprint 32 production repositioning completed locally: removed non-production project wording, replaced Sprint 32 contract with production Agent + BitPro tool-surface requirements, added `docs/architecture/17-bitpro-tool-adapter.md`, and fixed Agent market-summary tests to isolate OKX REST through injected settings.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, and pytest passed with 72 tests.

- `uv run pytest -q` -> 33 passed (5 new planner tests).
- `uv run ruff check` and `uv run mypy` -> clean.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 34 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 10 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 38 tests.
- `uv run pytest tests/test_market_ticker_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 39 tests.
- `uv run pytest tests/test_market_candles_tool.py tests/test_agent_planner.py -q` -> 12 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 44 tests.
- `uv run pytest tests/test_market_compare_tool.py tests/test_agent_planner.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 47 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 49 tests.
- `uv run pytest tests/test_live_candle_backtest.py tests/test_strategy_backtest_api.py tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 52 tests.
- `uv run pytest tests/test_agent_acceptance.py -q` -> 4 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 56 tests.
- `uv run pytest tests/test_cli.py tests/test_api.py -q` -> 17 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 57 tests.
- `uv run pytest tests/test_cli.py -q` -> 15 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 59 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_cli.py -q` -> 16 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 60 tests.
- `uv run pytest tests/test_bitpro_archive_backtest.py tests/test_cli.py -q` -> 19 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 63 tests.
- Server deployed SHA `bd58dd7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server BitPro archive backtest smoke passed through host `hypertrade`: `/research 研究BTC趋势突破` created research `srch_c51a2aabfa4a448194c8`; `/backtest --source bitpro --symbol BTC --bar 1H --limit 200` created `bt_26ee2b9416b24f5db66c` using `bitpro_sqlite_candles`, `BTC-USDT-SWAP`, `1H`, and 200 candles.
- Server deployed SHA `9f3fa0c`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server paper CLI smoke passed through host `hypertrade`: `/paper status` printed session, positions, fills, and events; `/paper pause` reported paused; `/paper resume` reported running.
- Server deployed SHA `cb02da6`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server Rich CLI smoke passed with `HYPERTRADE_RENDERER=rich hypertrade ask "看下ETH行情"`: output showed Rich panels and tables for run header, tool trace, `Agent Report`, and `Ticker`.
- Server deployed SHA `fee6be7`; server-local `GET 127.0.0.1:3334/api/health` returned OK.
- Server structured CLI smoke passed with `hypertrade ask "看下ETH行情"`: output showed `Agent Report`, `Ticker`, and multiple `Trend` sections rendered from structured trace outputs instead of raw Markdown.
- Server deployed SHA `e975d00`; server-local `GET 127.0.0.1:3334/api/health` and `GET 127.0.0.1:3333/api/health` returned OK.
- Server CLI shortcut smoke passed through host `hypertrade`: `/price ETH`, `/candles ETH --bar 1H --limit 50`, and `/compare ETH SOL --bar 4H --limit 100` returned exact ticker, K-line trend, and relative-strength output with `okx_rest` data source.
- Server CLI Agent status smoke passed with `hypertrade ask "看下ETH行情"`: output showed run creation, planning, tool execution, tool completion, final report generation, and completed report.
- Server deployed SHA `0afb197`; external `GET /api/health` returned OK.
- Server deployed SHA `48859cb`; external `GET /api/health` returned OK.
- Server live-candle backtest smoke passed with host `hypertrade`: `/research 研究ETH趋势突破` created `srch_987a780e0715494a99a3`, then `/backtest --live --symbol ETH --bar 1H --limit 100` created `bt_480d647199dd4d16b960` using `okx_rest_candles`, `ETH-USDT-SWAP`, `1H`, and 100 candles.
- Server deployed SHA `4ce55f8`; external `GET /api/health` returned OK.
- Server streaming smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_c6909801a50243649c32` and printed progress lines before the final report: `Run started`, `Tool call`, `Tool result`, and `Run completed`.
- Server deployed SHA `4de0a4b`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.compare [market]`.
- Server comparison smoke `hypertrade ask "比较 ETH 和 SOL 哪个更强"` produced run `run_7b35c4bfa1e34c899425` with `market_compare` calls, and the final answer included stable relative-strength ranking blocks for ETH/SOL across 1H, 4H, and 1D.
- Server deployed SHA `a258e05`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.candles [market]`.
- Server non-BTC trend smoke `hypertrade ask "看下ETH这两天走势"` produced run `run_f6d262efb67147eca905` with `market_ticker` and two `market_candles` calls, and the final answer included stable K-line trend blocks for `ETH-USDT-SWAP` 1H and 1D.
- Server deployed SHA `16b4ac6`; external `GET /api/health` returned OK.
- Server `/tools` slash command shows `market.ticker [market]`.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_d745abf2ec4246a38315` with `market_ticker`, `market_summary`, and `memory_write` tool calls.
- Server trace query verified `market_ticker` output `inst_id=ETH-USDT-SWAP`, `found=true`, `data_source=okx_rest`.
- Server deployed SHA `38f484f`; external `GET /api/health` returned OK.
- Server non-BTC CLI smoke `hypertrade ask "看下ETH行情"` produced run `run_674ab692117a443cb969` with `market_ticker` and `rag_search`, and the final answer included the stable exact ticker block for `ETH-USDT-SWAP`.
- Server deployed SHA `8d91748`; external `GET /api/health` returned OK.
- Server `/status` slash command smoke passed through host `hypertrade`.
- Server DeepSeek planner smoke passed with `hypertrade ask "看下比特币行情"`, producing run `run_363a592c965141a8b914` with `market_summary`, `rag_search`, `memory_search`, and `memory_write` tool calls.

## Verification Evidence (previous sprints)

- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 17 tests.
- `uv run pytest -q` -> 15 passed.
- `npm exec --yes pnpm@10 -- -C frontend test` -> 1 passed.
- `npm exec --yes pnpm@10 -- -C frontend build` -> production build passed.
- Playwright opened `http://127.0.0.1:3333`, logged in, and triggered an Agent market summary.
- Server deployment verified `http://47.79.36.92:3333/api/health`.
- Server authenticated `/api/harness/overview` through Nginx verified with 344 OKX SWAP tickers, 3 Agent runs, DeepSeek configured, 1 RAG document, 3 active Memory items, and 9 trace events.
- Server authenticated `/api/paper/status` through Nginx verified paper session `running`, equity `100000`, 10 positions, and 10 recent fills.
- Worker logs verified `paper_trading tick status=running fills=10`.
- Server deployment ran Alembic `0003_strategy_backtest`, rebuilt API/worker images, and deployed SHA `e38f3e3`.
- Server authenticated strategy/backtest smoke created research `srch_12196a7d8aff4fbda649`, backtest `bt_9fc24eda9bff4e02bde0`, strategy `momentum_breakout_v1`, return `0.019000`, trade count `1`, and confirmed `/api/harness/overview.strategy_lab`.
- `uv run pytest tests/test_cli.py -q` -> 3 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 20 tests.
- Server deployed SHA `8528171`; external `GET /api/health` returned OK.
- Server container CLI smoke passed with `docker compose exec -T -e HYPERTRADE_API_URL=http://127.0.0.1:3334 api hypertrade ask "请做行情归纳"`, producing run `run_24d3927e3e324496bac3` with `market.summary`, `rag.search`, and `memory.write` tool calls.
- `uv run pytest tests/test_cli.py -q` -> 6 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 23 tests.
- Server deployed SHA `d125406`; external `GET /api/health` returned OK.
- Server local standalone CLI smoke passed with `docker compose exec -T api hypertrade ask "请做行情归纳"`, producing run `run_77da091e850346fa9da7` with `market.summary`, `rag.search`, and `memory.write`.
- Server remote CLI smoke passed with `docker compose exec -T api hypertrade --remote http://127.0.0.1:3334 ask "请做行情归纳"`, producing run `run_d5b161b8d5a54f659328`.
- Server bare interactive CLI smoke passed with `printf ":q\n" | docker compose exec -T api hypertrade`.
- Server host CLI wrapper installed at `/usr/local/bin/hypertrade` via `deploy/deploy.sh`; root shell `hypertrade` enters chat and `hypertrade ask "请做行情归纳"` produced run `run_83db62b8e9184eadaab7`.
- `uv run pytest tests/test_cli.py -q` -> 9 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 25 tests.
- `uv run pytest tests/test_cli.py -q` -> 11 passed.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 28 tests.
- Implemented the read-only BitPro MCP adapter and Agent/API/backtest data-direct wiring: `bitpro_capabilities -> bitpro_health -> market_klines` preflight order, HyperTrade tools `bitpro.*`, `candle_source=bitpro_mcp`, and `/api/bitpro/*` admin endpoints.
- `./scripts/check.sh` -> frontend install/lint/test/build passed; ruff, mypy, pytest passed with 79 tests before deploy.
- Deployed SHA `1dab3c1` to production; server `/api/health` passed and `/api/harness/overview` reported BitPro adapter `mcp_read_only`, token configured, and live writes disabled.
- Production BitPro MCP smoke initially returned API 500 because the HyperTrade container used `127.0.0.1:8889`, which pointed to the container itself. Added structured BitPro 502 handling and Docker Compose host-gateway mapping so containerized deployments can use `host.docker.internal:8889`.

## Known Gaps

- OKX live WebSocket ingestion is implemented but not exercised against the remote server in this local run.
- V1 does not include automatic PostgreSQL backup.
- Sprint 13 adds live OKX candle input, but does not persist historical candles to PostgreSQL.
- OKX Testnet signed execution is implemented and documented, but this smoke pass did not place an external Testnet order; use `docs/runbooks/okx-testnet-order-smoke.md` for an explicit tiny-size order smoke.
- Public `http://47.79.36.92:3333/api/health` timed out from the current local environment after Sprint 15 deploy, while server-local Nginx/API health checks passed; likely requires cloud security group or caller IP whitelist review.

## Recommended Next Steps

1. Check cloud security group / caller IP whitelist for public port `3333`.
2. Add an archived candle source reader for BitPro file-store data if server data expands beyond SQLite.
3. Run an explicit OKX Testnet tiny-size order smoke after confirming the server `.env` testnet credentials and desired symbol/size.
