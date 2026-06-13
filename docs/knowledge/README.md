# HyperTrade Knowledge Base

This directory contains operator-facing knowledge that HyperTrade ingests into
RAG. Keep the files concise, source-bound, and safe to quote in Agent reports.

The worker scans this directory every 10 minutes and ingests changed Markdown
files into the RAG tables by file hash.

## Files

- `tool-usage-guide.md`: main operator guide for Agent tools, CLI/API checks,
  BitPro MCP usage, risk boundaries, tests, and deployment smoke.
- `memory-policy.md`: what Memory may store, how it is tagged, and how to
  search or disable it.
- `rag-usage.md`: how curated Markdown becomes searchable context.
- `strategy-research-playbook.md`: local strategy experiment workflow,
  evidence expectations, and `strategy_knowledge` memory sedimentation.

## Writing Rules

- Do not store secrets, tokens, account credentials, or production `.env` values.
- Prefer factual operational notes over broad trading claims.
- Keep BitPro references tied to MCP/API tools, not direct database access.
- Strategy and backtest notes remain research evidence, not investment advice.
