# RAG Usage

HyperTrade RAG reads Markdown files under `docs/knowledge` and stores chunk metadata in PostgreSQL.

Use paths:

- CLI: `/rag <query>`
- API: `GET /api/rag/search?query=<query>&limit=5`
- Frontend: `/harness` RAG search panel
- Agent: `rag_search` tool

Each hit should be treated as a citation candidate and includes `source_path`, `title`, `chunk_index`, `score`, and `content_preview`.

When Qwen embedding credentials are unavailable, deterministic embeddings keep local tests stable.

