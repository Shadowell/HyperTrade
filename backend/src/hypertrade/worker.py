import asyncio
import logging

from hypertrade.config import get_settings
from hypertrade.db import Database
from hypertrade.market.client import MarketIngestor
from hypertrade.market.repository import MarketRepository
from hypertrade.rag.service import RagService

logger = logging.getLogger("hypertrade.worker")


async def rag_scanner_loop(db: Database) -> None:
    settings = get_settings()
    service = RagService(db, knowledge_dir=settings.knowledge_dir)
    while True:
        result = service.scan_once()
        logger.info("rag_scan scanned=%s ingested=%s", result.scanned_files, result.ingested_files)
        await asyncio.sleep(settings.rag_scan_interval_seconds)


async def market_ingestion_loop(db: Database) -> None:
    settings = get_settings()
    ingestor = MarketIngestor(settings, MarketRepository(db))
    await ingestor.ingest_ws_forever()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = Database(settings.database_url)
    await asyncio.gather(rag_scanner_loop(db), market_ingestion_loop(db))


if __name__ == "__main__":
    asyncio.run(main())
