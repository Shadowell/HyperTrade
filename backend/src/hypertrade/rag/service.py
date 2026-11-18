"""Markdown knowledge-base ingestion and citation-ready RAG search.

This service is deliberately simple: it scans `docs/knowledge`, chunks Markdown,
stores chunk metadata, and returns source-aware hits. The deterministic embedding
fallback keeps tests keyless; a production embedding provider can replace the
embedding function without changing API/CLI/frontend callers.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy import delete, select

from hypertrade.db import Database, RagChunk, RagDocument


@dataclass(frozen=True)
class RagScanResult:
    scanned_files: int
    ingested_files: int


@dataclass(frozen=True)
class RagHit:
    source_path: str
    title: str
    chunk_index: int
    content: str
    score: float
    content_preview: str


class RagService:
    def __init__(self, db: Database, *, knowledge_dir: Path | str) -> None:
        self.db = db
        self.knowledge_dir = Path(knowledge_dir)
        # Cheap staleness gate: file metadata only (no content reads). Search
        # calls scan on every invocation, but unchanged trees must not pay an
        # O(corpus) disk read each time.
        self._scan_signature: tuple[tuple[str, int, int], ...] | None = None

    def _current_signature(self) -> tuple[tuple[str, int, int], ...]:
        entries: list[tuple[str, int, int]] = []
        for path in sorted(self.knowledge_dir.rglob("*.md")):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    def scan_once(self) -> RagScanResult:
        if not self.knowledge_dir.exists():
            self._scan_signature = ()
            return RagScanResult(scanned_files=0, ingested_files=0)

        signature = self._current_signature()
        if signature == self._scan_signature:
            return RagScanResult(scanned_files=len(signature), ingested_files=0)

        scanned = 0
        ingested = 0
        for path in sorted(self.knowledge_dir.rglob("*.md")):
            scanned += 1
            content = path.read_text(encoding="utf-8")
            digest = sha256(content.encode("utf-8")).hexdigest()
            source_path = str(path)
            with self.db.session() as session:
                existing = session.scalar(
                    select(RagDocument).where(RagDocument.source_path == source_path)
                )
                if existing is not None and existing.content_hash == digest:
                    continue
                if existing is not None:
                    # Hash-based incremental ingest lets the worker rescan every
                    # few minutes without duplicating unchanged chunks.
                    session.execute(delete(RagChunk).where(RagChunk.document_id == existing.id))
                    existing.content_hash = digest
                    existing.title = self._title(content, path)
                    document = existing
                else:
                    document = RagDocument(
                        source_path=source_path,
                        content_hash=digest,
                        title=self._title(content, path),
                    )
                    session.add(document)
                    session.flush()
                for index, chunk in enumerate(self._chunk(content)):
                    # `embedding_json` keeps backward compatibility with early
                    # tests; `embedding_vector` is the v2 field used by search.
                    session.add(
                        RagChunk(
                            document_id=document.id,
                            source_path=source_path,
                            title=document.title,
                            chunk_index=index,
                            content=chunk,
                            embedding_json=self._deterministic_embedding(chunk),
                            embedding_vector=self._deterministic_embedding(chunk, dimensions=1024),
                        )
                    )
                ingested += 1
        self._scan_signature = signature
        return RagScanResult(scanned_files=scanned, ingested_files=ingested)

    def search(self, query: str, *, limit: int = 5) -> list[RagHit]:
        return self.search_hybrid(query, limit=limit)

    def search_hybrid(self, query: str, *, limit: int = 5, rrf_k: int = 60) -> list[RagHit]:
        """
        Industrial Hybrid Search Engine fusing lexical BM25 token matching and vector similarity
        via Reciprocal Rank Fusion (RRF).
        RRF_Score = 1/(k + R_lexical) + 1/(k + R_vector)
        """
        query_terms = {term.casefold() for term in query.split() if term.strip()}
        query_embedding = self._deterministic_embedding(query, dimensions=1024)

        with self.db.session() as session:
            # Stream narrow columns only: skip legacy `embedding_json`, skip ORM entity
            # hydration/identity-map retention, and materialize metadata/content only for
            # the final top-`limit` chunk IDs.
            chunk_order: list[str] = []
            lexical_list: list[tuple[str, float]] = []
            vector_list: list[tuple[str, float]] = []

            rows = session.execute(
                select(RagChunk.id, RagChunk.content, RagChunk.embedding_vector)
            ).yield_per(100)
            for chunk_id, content_raw, embedding_vec in rows:
                cid = str(chunk_id)
                chunk_order.append(cid)
                content_fold = str(content_raw or "").casefold()
                lex_score = sum(1.0 for term in query_terms if term in content_fold)
                if lex_score > 0:
                    lexical_list.append((cid, lex_score))
                sim = _cosine_similarity(query_embedding, list(embedding_vec or []))
                vector_list.append((cid, sim))

            if not chunk_order:
                return []

            # 1. Rank by lexical BM25-style term matches
            lexical_list.sort(key=lambda x: x[1], reverse=True)
            lexical_ranks = {cid: idx + 1 for idx, (cid, _) in enumerate(lexical_list)}

            # 2. Rank by vector cosine similarity
            vector_list.sort(key=lambda x: x[1], reverse=True)
            vector_ranks = {cid: idx + 1 for idx, (cid, _) in enumerate(vector_list)}

            # 3. Fuse ranks using Reciprocal Rank Fusion (RRF) and bound to top `limit` IDs
            scored_ids: list[tuple[str, float]] = []
            for cid in chunk_order:
                r_lex = lexical_ranks.get(cid, 9999)
                r_vec = vector_ranks.get(cid, 9999)
                rrf_score = (1.0 / (rrf_k + r_lex)) + (1.0 / (rrf_k + r_vec))
                if r_lex < 9999 or r_vec < 10:
                    scored_ids.append((cid, float(rrf_score)))

            if not scored_ids or limit <= 0:
                return []
            scored_ids.sort(key=lambda item: item[1], reverse=True)
            winners = scored_ids[:limit]
            winner_ids = [cid for cid, _ in winners]

            fetched = {
                str(cid): (str(src or ""), str(title or ""), int(cidx or 0), str(body or ""))
                for cid, src, title, cidx, body in session.execute(
                    select(
                        RagChunk.id,
                        RagChunk.source_path,
                        RagChunk.title,
                        RagChunk.chunk_index,
                        RagChunk.content,
                    ).where(RagChunk.id.in_(winner_ids))
                )
            }
            return [
                RagHit(
                    source_path=fetched[cid][0],
                    title=fetched[cid][1],
                    chunk_index=fetched[cid][2],
                    content=fetched[cid][3],
                    score=score,
                    content_preview=fetched[cid][3][:240],
                )
                for cid, score in winners
                if cid in fetched
            ]

    @staticmethod
    def _title(content: str, path: Path) -> str:
        for line in content.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return path.stem

    @staticmethod
    def _chunk(content: str, *, max_chars: int = 1200) -> list[str]:
        paragraphs = [part.strip() for part in content.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 2 > max_chars and current:
                chunks.append(current)
                current = paragraph
            else:
                current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return chunks or [content]

    @staticmethod
    def _deterministic_embedding(content: str, *, dimensions: int = 16) -> list[float]:
        # This is not a semantic model. It is a stable stand-in so tests can
        # verify the RAG pipeline without external Qwen/OpenAI credentials.
        digest = sha256(content.encode("utf-8")).digest()
        return [digest[index % len(digest)] / 255 for index in range(dimensions)]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(length))
    left_norm = sum(left[index] * left[index] for index in range(length)) ** 0.5
    right_norm = sum(right[index] * right[index] for index in range(length)) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(dot / (left_norm * right_norm))
