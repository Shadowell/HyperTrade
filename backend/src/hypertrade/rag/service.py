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

    def scan_once(self) -> RagScanResult:
        if not self.knowledge_dir.exists():
            return RagScanResult(scanned_files=0, ingested_files=0)
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
        return RagScanResult(scanned_files=scanned, ingested_files=ingested)

    def search(self, query: str, *, limit: int = 5) -> list[RagHit]:
        query_terms = {term.casefold() for term in query.split() if term.strip()}
        query_embedding = self._deterministic_embedding(query, dimensions=1024)
        with self.db.session() as session:
            chunks = session.scalars(select(RagChunk)).all()
            scored: list[RagHit] = []
            for chunk in chunks:
                content_fold = chunk.content.casefold()
                # Hybrid score: lexical matches help short Chinese/English
                # queries, while cosine similarity gives vector-style behavior.
                term_score = sum(1 for term in query_terms if term in content_fold)
                vector_score = _cosine_similarity(query_embedding, chunk.embedding_vector or [])
                score = float(term_score) + vector_score
                if score > 0:
                    scored.append(
                        RagHit(
                            source_path=chunk.source_path,
                            title=chunk.title,
                            chunk_index=chunk.chunk_index,
                            content=chunk.content,
                            score=float(score),
                            content_preview=chunk.content[:240],
                        )
                    )
            return sorted(scored, key=lambda hit: hit.score, reverse=True)[:limit]

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
