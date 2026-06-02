from decimal import Decimal

from hypertrade.db import Database, MarketTicker, PaperFill, PaperPosition, PaperSession
from hypertrade.paper.service import PaperTradingService


def test_paper_service_bootstraps_default_session():
    db = Database("sqlite:///:memory:")
    db.create_all()

    session = PaperTradingService(db).ensure_default_session()

    assert session.id.startswith("paper_")
    assert session.status == "running"
    assert session.cash == "100000"
    with db.session() as db_session:
        assert db_session.get(PaperSession, session.id) is not None


def test_paper_service_run_once_creates_fills_and_positions():
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_ticker(db, "AAA-USDT-SWAP", "10", "1000", "4.2")
    _seed_ticker(db, "BBB-USDT-SWAP", "20", "900", "-4.5")

    result = PaperTradingService(db).run_once()

    assert result.status == "running"
    assert result.fill_count == 2
    with db.session() as session:
        fills = session.query(PaperFill).all()
        positions = session.query(PaperPosition).all()
        assert len(fills) == 2
        assert len(positions) == 2
        assert {position.side for position in positions} == {"long", "short"}


def test_paper_service_pause_prevents_new_trades():
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_ticker(db, "AAA-USDT-SWAP", "10", "1000", "4.2")
    service = PaperTradingService(db)

    paused = service.pause()
    result = service.run_once()

    assert paused["session"]["status"] == "paused"
    assert result.status == "paused"
    assert result.fill_count == 0


def test_paper_service_respects_max_positions():
    db = Database("sqlite:///:memory:")
    db.create_all()
    for index in range(12):
        _seed_ticker(db, f"AAA{index}-USDT-SWAP", "10", "1000", str(3 + index))

    result = PaperTradingService(db).run_once()

    assert result.fill_count == 10
    with db.session() as session:
        assert session.query(PaperPosition).count() == 10


def test_paper_service_close_symbol_realizes_pnl_and_closes_position():
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_ticker(db, "ETH-USDT-SWAP", "100", "1000", "4.2")
    service = PaperTradingService(db)
    service.run_once()
    _update_ticker(db, "ETH-USDT-SWAP", "110")

    result = service.close(symbol="ETH")

    assert result["closed_count"] == 1
    assert result["closed"][0]["inst_id"] == "ETH-USDT-SWAP"
    with db.session() as session:
        position = session.query(PaperPosition).one()
        paper_session = session.query(PaperSession).one()
        assert position.status == "closed"
        assert paper_session.realized_pnl > 0
        assert session.query(PaperFill).count() == 2


def test_paper_service_reset_archives_session_and_creates_new_one():
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = PaperTradingService(db)
    original = service.ensure_default_session()

    result = service.reset()

    assert result["session"]["id"] != original.id
    assert result["session"]["status"] == "running"
    assert service.ensure_default_session().id == result["session"]["id"]
    with db.session() as session:
        statuses = {row.status for row in session.query(PaperSession).all()}
        assert statuses == {"reset", "running"}


def _seed_ticker(
    db: Database,
    inst_id: str,
    last: str,
    volume: str,
    change: str,
) -> None:
    with db.session() as session:
        session.add(
            MarketTicker(
                inst_id=inst_id,
                inst_type="SWAP",
                last=Decimal(last),
                volume_ccy_24h=Decimal(volume),
                change_utc0_pct=Decimal(change),
                raw={},
            )
        )


def _update_ticker(db: Database, inst_id: str, last: str) -> None:
    with db.session() as session:
        ticker = session.query(MarketTicker).filter(MarketTicker.inst_id == inst_id).one()
        ticker.last = Decimal(last)
