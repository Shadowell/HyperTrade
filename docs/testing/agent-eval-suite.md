# Agent Eval Suite

## Purpose

The Agent eval suite is deterministic and local-first. It verifies Agent
engineering behavior without calling external model judges, paid eval services,
or live trading systems.

Sprint 53 expands the original Sprint 31 status checks into source-of-truth and
anti-hallucination guardrails. Each case describes a prompt shape, required and
forbidden tools, required and forbidden report fragments, expected source ids,
and missing-data expectations. The suite checks behavior contracts instead of
exact prose snapshots.

## Cases

| Case | Expectation |
| --- | --- |
| `tool_selection` | Market prompts select market tools before final reports. |
| `rag_citation` | RAG hits include citation metadata. |
| `memory_behavior` | Memory writes dedupe and search by query/tag/kind. |
| `risk_refusal` | Mainnet and oversized order intents are blocked. |
| `testnet_order_safety` | Signed execution is Testnet-only and stores redacted request data. |
| `strategy_library_history_source` | Strategy-history prompts call `strategy_library_search` and cite `strategy_knowledge` Memory evidence instead of model recall. |
| `bitpro_backtest_page_parity` | BitPro result-ranking prompts call `bitpro_backtest_list_results` and report `total_return_pct` from BitPro result rows, not memory or annualized return substitutions. |
| `missing_artifact_disclosure` | Specific BitPro result-detail prompts keep unavailable artifacts visible instead of smoothing over missing rows. |
| `paper_monitor_read_only` | Paper-monitor prompts stay read-only, surface alerts, and preserve missing per-strategy metric gaps. |
| `compact_report_rendering` | Default report rendering avoids low-signal trace, contract, and raw inventory noise. |
| `live_order_history_source` | Live order-history prompts call `bitpro_live_order_history` and never substitute all-market summaries. |
| `live_strategy_performance_source` | Live strategy performance prompts call `bitpro_live_strategy_performance` and rank BitPro `return_pct` evidence. |

## Case Contract

Each deterministic case includes:

- `prompt`
- `required_tools`
- `forbidden_tools`
- `required_report_fragments`
- `forbidden_report_fragments`
- `expected_source_ids`
- `missing_data_expectations`

Failures are reported as findings such as `required_tool_missing`,
`forbidden_tool_used`, `forbidden_report_fragment`, `source_id_missing`, and
`missing_data_not_reported`.

## Adding Cases

When a future Agent-visible tool or report behavior lands:

1. Add or update an `AgentEvalCase` in `backend/src/hypertrade/evals/service.py`.
2. Add a deterministic default `EvalObservation` that passes without external
   network, provider keys, or live BitPro state.
3. Add a focused negative test in `tests/test_agent_eval_suite.py` if the new
   behavior has an important hallucination or source-substitution failure mode.
4. Prefer fixture helpers such as `tool_output_fixture` and
   `strategy_memory_fixture` over large prose snapshots.

## Surfaces

- API: `GET /api/evals/status`
- CLI: `/evals`
- Tests: `tests/test_agent_eval_suite.py`

## Verification

```bash
uv run pytest tests/test_agent_acceptance.py -q
uv run pytest tests/test_agent_eval_suite.py -q
uv run pytest tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```
