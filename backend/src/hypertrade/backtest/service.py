import asyncio
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select

from hypertrade.backtest.bitpro import BitProKlineArchive
from hypertrade.backtest.engine import BacktestEngine
from hypertrade.config import Settings, get_settings
from hypertrade.db import BacktestRun, Database
from hypertrade.market.client import OkxRestClient
from hypertrade.market.okx import OkxCandle
from hypertrade.strategy.sdk import Candle, sample_candles
from hypertrade.strategy.service import StrategyResearchService


class BacktestService:
    def __init__(self, db: Database, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings
        self.engine = BacktestEngine()

    def run(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        candles: list[Candle] | None = None,
        initial_cash: Decimal = Decimal("100000"),
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]:
        if research_id:
            research = StrategyResearchService(self.db).get(research_id)
            if research is None:
                raise KeyError(research_id)
            strategy_key = str(research["strategy_key"])
        data_source = "provided_candles" if candles else "sample_candles"
        inst_id = ""
        normalized_bar = _normalize_okx_bar(bar)
        selected_source = "okx" if use_live_candles else candle_source.strip().lower()
        if selected_source == "okx":
            inst_id = _normalize_swap_inst_id(symbol)
            okx_candles = self._fetch_okx_candles(inst_id, normalized_bar, candle_limit)
            candles = _okx_candles_to_strategy_candles(okx_candles)
            data_source = "okx_rest_candles"
        elif selected_source == "bitpro":
            inst_id = _normalize_swap_inst_id(symbol)
            candles = self._fetch_bitpro_candles(
                symbol=symbol,
                bar=normalized_bar,
                limit=candle_limit,
            )
            data_source = "bitpro_sqlite_candles"
        result = self.engine.run(
            strategy_key=strategy_key,
            candles=candles or sample_candles(),
            initial_cash=initial_cash,
        )
        report_json = dict(result.report_json)
        report_json.update(
            {
                "data_source": data_source,
                "inst_id": inst_id,
                "bar": normalized_bar if selected_source in {"okx", "bitpro"} else "",
                "candle_count": len(candles or sample_candles()),
            }
        )
        report_markdown = _append_data_source(
            result.report_markdown,
            data_source=data_source,
            inst_id=inst_id,
            bar=normalized_bar if selected_source in {"okx", "bitpro"} else "",
            candle_count=len(candles or sample_candles()),
        )
        with self.db.session() as session:
            run = BacktestRun(
                research_id=research_id,
                strategy_key=result.strategy_key,
                status="completed",
                start_cash=result.start_cash,
                end_value=result.end_value,
                total_return_pct=result.total_return_pct,
                max_drawdown_pct=result.max_drawdown_pct,
                trade_count=result.trade_count,
                report_markdown=report_markdown,
                report_json=report_json,
            )
            session.add(run)
            session.flush()
            return _run_to_dict(run)

    def _fetch_okx_candles(self, inst_id: str, bar: str, limit: int) -> list[OkxCandle]:
        settings = self.settings or get_settings()
        safe_limit = max(6, min(limit, 300))
        return asyncio.run(
            OkxRestClient(settings).fetch_candles(inst_id=inst_id, bar=bar, limit=safe_limit)
        )

    def _fetch_bitpro_candles(self, *, symbol: str, bar: str, limit: int) -> list[Candle]:
        settings = self.settings or get_settings()
        if not settings.bitpro_sqlite_path:
            raise FileNotFoundError("BITPRO_SQLITE_PATH is not configured")
        candles = BitProKlineArchive(settings.bitpro_sqlite_path).read_candles(
            symbol=symbol,
            bar=bar,
            limit=limit,
        )
        if not candles:
            raise ValueError(f"No BitPro candles found for {symbol} {bar}")
        return candles

    def latest(self) -> dict[str, Any] | None:
        with self.db.session() as session:
            run = session.scalar(
                select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(1)
            )
            return _run_to_dict(run) if run else None

    def list_recent(self, *, limit: int = 10) -> list[dict[str, Any]]:
        with self.db.session() as session:
            runs = session.scalars(
                select(BacktestRun).order_by(desc(BacktestRun.created_at)).limit(limit)
            ).all()
            return [_run_to_dict(run) for run in runs]


def _run_to_dict(run: BacktestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "research_id": run.research_id,
        "strategy_key": run.strategy_key,
        "status": run.status,
        "metrics": {
            "start_cash": str(run.start_cash),
            "end_value": str(run.end_value),
            "total_return_pct": str(run.total_return_pct),
            "max_drawdown_pct": str(run.max_drawdown_pct),
            "trade_count": run.trade_count,
        },
        "report_markdown": run.report_markdown,
        "report_json": run.report_json,
        "created_at": run.created_at.isoformat(),
    }


def _okx_candles_to_strategy_candles(okx_candles: list[OkxCandle]) -> list[Candle]:
    ordered = sorted(okx_candles, key=lambda candle: candle.open_time)
    return [
        Candle(
            timestamp=candle.open_time.isoformat(),
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume_ccy,
        )
        for candle in ordered
    ]


def _normalize_swap_inst_id(symbol: str) -> str:
    value = symbol.strip().upper().replace("_", "-").replace("/", "-")
    if not value:
        return "BTC-USDT-SWAP"
    if value.endswith("-SWAP"):
        return value
    if value.endswith("-USDT"):
        return f"{value}-SWAP"
    if "-" not in value:
        return f"{value}-USDT-SWAP"
    return f"{value}-SWAP"


def _normalize_okx_bar(bar: str) -> str:
    value = bar.strip()
    if not value:
        return "1H"
    if value.lower().endswith("h"):
        return f"{value[:-1]}H"
    if value.lower().endswith("d"):
        return f"{value[:-1]}D"
    return value


def _append_data_source(
    report_markdown: str,
    *,
    data_source: str,
    inst_id: str,
    bar: str,
    candle_count: int,
) -> str:
    lines = [
        report_markdown,
        "",
        "## Data Source",
        "",
        f"- Source: {data_source}",
        f"- Candle count: {candle_count}",
    ]
    if inst_id:
        lines.append(f"- Instrument: {inst_id}")
    if bar:
        lines.append(f"- Bar: {bar}")
    return "\n".join(lines)
