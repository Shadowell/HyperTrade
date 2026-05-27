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
    content: str
    score: float


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
                    session.add(
                        RagChunk(
                            document_id=document.id,
                            source_path=source_path,
                            chunk_index=index,
                            content=chunk,
                            embedding_json=self._deterministic_embedding(chunk),
                        )
                    )
                ingested += 1
        return RagScanResult(scanned_files=scanned, ingested_files=ingested)

    def search(self, query: str, *, limit: int = 5) -> list[RagHit]:
        query_terms = {term.casefold() for term in query.split() if term.strip()}
        with self.db.session() as session:
            chunks = session.scalars(select(RagChunk)).all()
            scored: list[RagHit] = []
            for chunk in chunks:
                content_fold = chunk.content.casefold()
                score = sum(1 for term in query_terms if term in content_fold)
                if score > 0:
                    scored.append(
                        RagHit(
                            source_path=chunk.source_path,
                            content=chunk.content,
                            score=float(score),
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
        digest = sha256(content.encode("utf-8")).digest()
        return [digest[index % len(digest)] / 255 for index in range(dimensions)]
