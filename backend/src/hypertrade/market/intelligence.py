from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hypertrade.config import Settings, get_settings
from hypertrade.market.client import OkxRestClient

CURATED_CONTEXT_PATH = Path("docs/knowledge/market-intelligence-curated.md")
OKX_INTELLIGENCE_SOURCE_PATH = "/api/v5/public/funding-rate + /api/v5/public/open-interest"


@dataclass(frozen=True)
class MarketIntelligenceResult:
    source: str
    source_path: str
    symbol: str
    as_of: str
    freshness_seconds: int
    metrics: dict[str, str]
    missing_fields: list[str]
    sample: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_path": self.source_path,
            "symbol": self.symbol,
            "as_of": self.as_of,
            "freshness_seconds": self.freshness_seconds,
            "metrics": self.metrics,
            "missing_fields": self.missing_fields,
            "sample": self.sample,
        }


class MarketIntelligenceRepository:
    def __init__(self, curated_path: Path | str = CURATED_CONTEXT_PATH) -> None:
        self.curated_path = Path(curated_path)

    def curated_context(self, *, symbol: str, now: datetime) -> MarketIntelligenceResult:
        sample = self._read_curated_sample()
        if not sample:
            sample = [
                (
                    "funding/open-interest context: treat derivatives positioning as "
                    "risk context, not a standalone trade signal."
                )
            ]
        return MarketIntelligenceResult(
            source="curated.market_context",
            source_path=self.curated_path.as_posix(),
            symbol=symbol,
            as_of=now.isoformat(),
            freshness_seconds=0,
            metrics={"context_items": str(len(sample))},
            missing_fields=[],
            sample=sample[:3],
        )

    def _read_curated_sample(self) -> list[str]:
        try:
            text = self.curated_path.read_text(encoding="utf-8")
        except OSError:
            return []
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            while line.startswith(("-", "*")):
                line = line[1:].strip()
            if line:
                lines.append(line)
        return lines[:5]


class MarketIntelligenceService:
    def __init__(
        self,
        *,
        okx_client: Any | None = None,
        repository: MarketIntelligenceRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings
        self.okx_client = okx_client
        self.repository = repository or MarketIntelligenceRepository()

    def collect(self, *, symbol: str, include_curated: bool = True) -> dict[str, Any]:
        now = datetime.now(UTC)
        inst_id = normalize_swap_inst_id(symbol)
        results = [self._okx_funding_open_interest(inst_id=inst_id, now=now)]
        if include_curated:
            results.append(self.repository.curated_context(symbol=inst_id, now=now))
        return {
            "symbol": symbol,
            "inst_id": inst_id,
            "source_count": len(results),
            "results": [result.to_dict() for result in results],
            "as_of_utc": now.isoformat(),
        }

    def _okx_funding_open_interest(
        self,
        *,
        inst_id: str,
        now: datetime,
    ) -> MarketIntelligenceResult:
        missing_fields: list[str] = []
        metrics: dict[str, str] = {}
        sample: list[str] = []
        timestamps: list[datetime] = []

        try:
            funding = self._run_async(self._client().fetch_funding_rate(inst_id=inst_id))
            open_interest = self._run_async(self._client().fetch_open_interest(inst_id=inst_id))
        except Exception as exc:
            return MarketIntelligenceResult(
                source="okx_public.funding_open_interest",
                source_path=OKX_INTELLIGENCE_SOURCE_PATH,
                symbol=inst_id,
                as_of=now.isoformat(),
                freshness_seconds=0,
                metrics={},
                missing_fields=[
                    "funding_rate",
                    "next_funding_rate",
                    "open_interest_contracts",
                    "open_interest_ccy",
                ],
                sample=[f"unavailable: {str(exc)[:120]}"],
            )

        funding_rate = _string_value(funding.get("fundingRate"))
        if funding_rate:
            metrics["funding_rate"] = funding_rate
            sample.append(f"funding_rate={funding_rate}")
        else:
            missing_fields.append("funding_rate")

        next_funding_rate = _string_value(funding.get("nextFundingRate"))
        if next_funding_rate:
            metrics["next_funding_rate"] = next_funding_rate
            sample.append(f"next_funding_rate={next_funding_rate}")
        else:
            missing_fields.append("next_funding_rate")

        open_interest_contracts = _string_value(open_interest.get("oi"))
        if open_interest_contracts:
            metrics["open_interest_contracts"] = open_interest_contracts
            sample.append(f"open_interest_contracts={open_interest_contracts}")
        else:
            missing_fields.append("open_interest_contracts")

        open_interest_ccy = _string_value(open_interest.get("oiCcy"))
        if open_interest_ccy:
            metrics["open_interest_ccy"] = open_interest_ccy
            sample.append(f"open_interest_ccy={open_interest_ccy}")
        else:
            missing_fields.append("open_interest_ccy")

        for value in (funding.get("fundingTime"), open_interest.get("ts")):
            parsed = _parse_okx_timestamp(value)
            if parsed is not None:
                timestamps.append(parsed)
        as_of = max(timestamps) if timestamps else now

        return MarketIntelligenceResult(
            source="okx_public.funding_open_interest",
            source_path=OKX_INTELLIGENCE_SOURCE_PATH,
            symbol=inst_id,
            as_of=as_of.isoformat(),
            freshness_seconds=max(0, int((now - as_of).total_seconds())),
            metrics=metrics,
            missing_fields=missing_fields,
            sample=sample[:5],
        )

    def _client(self) -> Any:
        if self.okx_client is None:
            settings = self.settings if self.settings is not None else get_settings()
            self.okx_client = OkxRestClient(settings)
        return self.okx_client

    @staticmethod
    def _run_async(awaitable: Any) -> Any:
        return asyncio.run(awaitable)


def normalize_swap_inst_id(symbol: str) -> str:
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


def _parse_okx_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _string_value(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value)
