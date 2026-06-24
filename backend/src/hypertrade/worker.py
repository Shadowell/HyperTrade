import asyncio
import logging
from typing import Any

from hypertrade.bitpro.mcp import BitProMcpClient, BitProToolAdapter
from hypertrade.config import Settings, get_settings
from hypertrade.db import Database
from hypertrade.market.client import MarketIngestor
from hypertrade.market.repository import MarketRepository
from hypertrade.monitoring import MonitorService
from hypertrade.paper.service import PaperTradingService
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


async def market_rest_supplement_loop(db: Database) -> None:
    settings = get_settings()
    ingestor = MarketIngestor(settings, MarketRepository(db))
    while True:
        try:
            count = await ingestor.ingest_rest_once()
            logger.info("okx_rest_supplement tickers=%s", count)
        except Exception:
            logger.exception("okx_rest_supplement failed")
        await asyncio.sleep(settings.okx_rest_supplement_interval_seconds)


async def paper_trading_loop(db: Database) -> None:
    settings = get_settings()
    service = PaperTradingService(db, settings=settings)
    while True:
        try:
            result = service.run_once()
            logger.info("paper_trading tick status=%s fills=%s", result.status, result.fill_count)
        except Exception:
            logger.exception("paper_trading failed")
        await asyncio.sleep(settings.paper_loop_interval_seconds)


def monitor_scheduler_once(
    db: Database,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or get_settings()
    if not active_settings.monitor_scheduler_enabled:
        return {
            "status": "disabled",
            "ran": [],
            "skipped": [],
            "failed": [],
        }
    adapter = BitProToolAdapter(BitProMcpClient(settings=active_settings))
    return MonitorService(db, bitpro_adapter=adapter).run_due_monitors()


async def monitor_scheduler_loop(db: Database) -> None:
    settings = get_settings()
    while True:
        try:
            result = monitor_scheduler_once(db, settings=settings)
            logger.info(
                "monitor_scheduler status=%s ran=%s skipped=%s failed=%s",
                result.get("status"),
                len(result.get("ran", [])),
                len(result.get("skipped", [])),
                len(result.get("failed", [])),
            )
        except Exception:
            logger.exception("monitor_scheduler failed")
        await asyncio.sleep(settings.monitor_loop_interval_seconds)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    db = Database(settings.database_url)
    tasks = [
        rag_scanner_loop(db),
        market_ingestion_loop(db),
        market_rest_supplement_loop(db),
    ]
    if settings.paper_enabled:
        tasks.append(paper_trading_loop(db))
    if settings.monitor_scheduler_enabled:
        tasks.append(monitor_scheduler_loop(db))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
