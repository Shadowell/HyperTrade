# Sprint 26 Contract: RAG v2 With Citations

## Goal

Make RAG outputs citation-ready and closer to enterprise Agent retrieval patterns.

## Scope

- Store chunk title, chunk index, deterministic vector fallback, and production vector field.
- Return `source_path`, `title`, `chunk_index`, `score`, and content preview for each hit.
- Add API `GET /api/rag/search`.
- Add CLI `/rag <query>`.
- Add citation block support in Agent planner reports.

## Acceptance

- Local tests pass without Qwen key using deterministic embeddings.
- RAG hits expose source metadata for citations.
- Agent reports can include citation sources.
- API, CLI, and frontend can query RAG hits.

## Verification

```bash
uv run pytest tests/test_rag_memory.py tests/test_api.py tests/test_cli.py -q
./scripts/check.sh
```

