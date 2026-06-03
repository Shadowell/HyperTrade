# Agent Eval Suite

## Purpose

The Sprint 31 eval suite is deterministic and local-first. It verifies Agent engineering behavior without calling external model judges.

## Cases

| Case | Expectation |
| --- | --- |
| `tool_selection` | Market prompts select market tools before final reports. |
| `rag_citation` | RAG hits include citation metadata. |
| `memory_behavior` | Memory writes dedupe and search by query/tag/kind. |
| `risk_refusal` | Mainnet and oversized order intents are blocked. |
| `testnet_order_safety` | Signed execution is Testnet-only and stores redacted request data. |

## Surfaces

- API: `GET /api/evals/status`
- CLI: `/evals`
- Frontend: `/harness` Agent eval panel

## Verification

```bash
uv run pytest tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

