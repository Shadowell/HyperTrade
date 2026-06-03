# 05 RAG + pgvector / RAG 与 pgvector

## English

RAG ingests Markdown from `docs/knowledge`. The worker scans every 10 minutes, compares file hashes, and rewrites chunks only when content changes.

Storage:

- `rag_documents`: source path, hash, title
- `rag_chunks`: chunk content, source path, deterministic local embedding JSON
- migration adds a `vector(1024)` column for pgvector production use

Sprint 01 uses deterministic embeddings in tests and keeps Qwen `text-embedding-v4` as the production provider path.

## Sprint 26 Update

RAG hits are now citation-ready. Each search result returns:

- `source_path`
- `title`
- `chunk_index`
- `score`
- `content_preview`

The API exposes `GET /api/rag/search?query=...`, CLI exposes `/rag <query>`, and `/harness` includes a RAG search panel. The deterministic vector fallback remains available for local tests without Qwen credentials.

## 中文

RAG 从 `docs/knowledge` 导入 Markdown。worker 每 10 分钟扫描一次，根据文件 hash 判断是否需要增量更新。

存储：

- `rag_documents`：来源路径、hash、标题
- `rag_chunks`：chunk 内容、来源路径、本地确定性 embedding JSON
- migration 增加 `vector(1024)` 列，供生产 pgvector 使用

Sprint 01 测试使用确定性 embedding，生产配置路径保留 Qwen `text-embedding-v4`。

## Sprint 26 更新

RAG 命中现在可以直接作为引用来源。每条结果返回：

- `source_path`
- `title`
- `chunk_index`
- `score`
- `content_preview`

API 提供 `GET /api/rag/search?query=...`，CLI 提供 `/rag <query>`，`/harness` 增加 RAG 搜索面板。本地无 Qwen key 时继续使用确定性向量 fallback。
