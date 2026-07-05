# Sprint 75 - Global Market Data Integration / 全球市场数据集成

## Goal

Integrate free global market data sources to support HyperTrade's world model with
cross-asset state evidence. The world model currently relies on OKX crypto data;
this Sprint adds US equities, volatility indices, rates, FX, and commodities
through yfinance (primary) and Alpha Vantage (fallback) adapters.

## Background

The world model roadmap (`docs/architecture/22-world-model-development-roadmap.md`)
specifies that market state should be global, not crypto-only:

- `risk_regime`: risk_on / risk_off / mixed / stress / unknown
- `liquidity_regime`: loose / neutral / tight / unknown
- `volatility_regime`: calm / elevated / stressed / unknown
- `dollar_pressure`: weak / neutral / strong / unknown
- `rates_pressure`: falling / neutral / rising / unknown
- `cross_asset_signal`: supportive / conflicting / hostile / unknown

Phase 1 allows fixtures for unavailable sources, but missing data must be
explicit. This Sprint replaces fixture global market state with live free data.

## In Scope

### Core Infrastructure

1. **Global Market Data Adapter**
   - `backend/src/hypertrade/global_market/` module
   - `schemas.py`: asset classes, tickers, regimes
   - `sources/`: vendor adapters
   - `collectors.py`: parallel data collection
   - `analyzers.py`: regime classification
   - `service.py`: orchestration

2. **Free Data Source Adapters**
   - **yfinance** (primary, no API key):
     - US equities: `^GSPC` (S&P 500), `^IXIC` (Nasdaq), `^RUT` (Russell 2000)
     - Volatility: `^VIX` (CBOE Volatility Index)
     - FX: `DX-Y.NYB` (US Dollar Index)
     - Commodities: `GC=F` (Gold Futures), `CL=F` (Crude Oil Futures)
     - Rates: `^TNX` (10Y Treasury Yield), `^FVX` (5Y Treasury Yield)
   - **Alpha Vantage** (fallback, free tier 25 requests/day):
     - Same tickers through `TIME_SERIES_DAILY` and `GLOBAL_QUOTE`
     - Rate limit handling with automatic yfinance fallback

3. **World Model Integration**
   - Update `world_model/collectors.py` to call `GlobalMarketService`
   - Replace fixture global market state with live data
   - Preserve `missing_data` markers when sources fail
   - Add `global_market_source_refs` with vendor, ticker, timestamp

4. **Agent Tools**
   - Add `global_market_snapshot` planner tool (read-only)
   - ToolRegistry entry with `category=market, scope=read, approval=none`
   - Report block rendering for global market regime

5. **API Endpoints**
   - `GET /api/global-market/snapshot` - current global market state
   - `GET /api/global-market/tickers` - supported ticker list
   - Admin endpoint for source health

### Supported Asset Classes

| Asset Class | Ticker | yfinance | Alpha Vantage | Purpose |
| --- | --- | --- | --- | --- |
| US Equities | `^GSPC` | ✅ | ✅ | S&P 500 - broad US market |
| US Equities | `^IXIC` | ✅ | ✅ | Nasdaq - tech sentiment |
| US Equities | `^RUT` | ✅ | ✅ | Russell 2000 - small cap risk |
| Volatility | `^VIX` | ✅ | ✅ | Fear index |
| FX | `DX-Y.NYB` | ✅ | ❌ | Dollar strength |
| Commodities | `GC=F` | ✅ | ✅ | Gold - safe haven |
| Commodities | `CL=F` | ✅ | ✅ | Crude oil - energy |
| Rates | `^TNX` | ✅ | ❌ | 10Y Treasury yield |
| Rates | `^FVX` | ✅ | ❌ | 5Y Treasury yield |

### Regime Classification Logic

**Risk Regime:**
- `risk_on`: S&P +1%, VIX < 15, small caps outperform
- `risk_off`: S&P -1%, VIX > 25, small caps underperform
- `stress`: S&P -2%, VIX > 35
- `mixed`: conflicting signals
- `unknown`: insufficient data

**Volatility Regime:**
- `calm`: VIX < 15
- `elevated`: 15 ≤ VIX < 25
- `stressed`: VIX ≥ 25

**Dollar Pressure:**
- `strong`: DXY > 105 or +1% intraday
- `weak`: DXY < 100 or -1% intraday
- `neutral`: otherwise

**Rates Pressure:**
- `rising`: 10Y yield +10bp from prior close
- `falling`: 10Y yield -10bp from prior close
- `neutral`: within 10bp

**Cross-Asset Signal:**
- `supportive`: equities up, VIX down, gold down, dollar neutral/weak
- `conflicting`: mixed signals (e.g. equities up but VIX up)
- `hostile`: equities down, VIX up, gold up, dollar strong

## Out of Scope

- Real-time streaming (use daily close or latest intraday quote)
- Paid data sources (Bloomberg, Refinitiv)
- Asia market hours data if yfinance/Alpha Vantage don't support
- Historical backfill beyond 30 days
- Custom indicator calculations (use raw price/volume only)
- Trading global markets (read-only evidence only)

## Implementation Plan

### Step 1: Global Market Module Structure

```python
backend/src/hypertrade/global_market/
├── __init__.py
├── schemas.py              # AssetClass, Ticker, RegimeState
├── sources/
│   ├── __init__.py
│   ├── base.py            # GlobalMarketSource protocol
│   ├── yfinance_source.py # yfinance adapter
│   └── alpha_vantage_source.py  # Alpha Vantage fallback
├── collectors.py          # Parallel ticker collection
├── analyzers.py           # Regime classification
└── service.py             # GlobalMarketService orchestration
```

### Step 2: yfinance Adapter (No API Key)

```python
# backend/src/hypertrade/global_market/sources/yfinance_source.py
import yfinance as yf
from datetime import datetime

class YFinanceSource:
    def get_ticker(self, symbol: str) -> dict:
        """Fetch latest quote for symbol."""
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")  # last 2 days
        if hist.empty:
            return {"error": "no_data", "symbol": symbol}
        
        latest = hist.iloc[-1]
        prior = hist.iloc[-2] if len(hist) > 1 else latest
        
        return {
            "symbol": symbol,
            "price": float(latest["Close"]),
            "change_pct": ((latest["Close"] - prior["Close"]) / prior["Close"] * 100),
            "volume": int(latest["Volume"]),
            "timestamp": latest.name.isoformat(),
            "source": "yfinance",
        }
```

### Step 3: Alpha Vantage Fallback (Free Tier)

```python
# backend/src/hypertrade/global_market/sources/alpha_vantage_source.py
import os
import requests

class AlphaVantageSource:
    def __init__(self):
        self.api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url = "https://www.alphavantage.co/query"
    
    def get_ticker(self, symbol: str) -> dict:
        """Fetch global quote with rate limit handling."""
        if not self.api_key:
            return {"error": "no_api_key", "symbol": symbol}
        
        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": self.api_key,
        }
        
        try:
            resp = requests.get(self.base_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if "Note" in data or "Information" in data:
                # Rate limit hit
                return {"error": "rate_limit", "symbol": symbol}
            
            quote = data.get("Global Quote", {})
            if not quote:
                return {"error": "no_data", "symbol": symbol}
            
            return {
                "symbol": symbol,
                "price": float(quote.get("05. price", 0)),
                "change_pct": float(quote.get("10. change percent", "0").rstrip("%")),
                "volume": int(quote.get("06. volume", 0)),
                "timestamp": quote.get("07. latest trading day"),
                "source": "alpha_vantage",
            }
        except Exception as e:
            return {"error": str(e), "symbol": symbol}
```

### Step 4: Regime Analyzer

```python
# backend/src/hypertrade/global_market/analyzers.py
from typing import Literal

RiskRegime = Literal["risk_on", "risk_off", "stress", "mixed", "unknown"]
VolatilityRegime = Literal["calm", "elevated", "stressed", "unknown"]

class RegimeAnalyzer:
    def classify_risk_regime(
        self,
        sp500_change: float | None,
        vix_level: float | None,
        russell_change: float | None,
    ) -> RiskRegime:
        if sp500_change is None or vix_level is None:
            return "unknown"
        
        if sp500_change < -2.0 or vix_level > 35:
            return "stress"
        elif sp500_change < -1.0 or vix_level > 25:
            return "risk_off"
        elif sp500_change > 1.0 and vix_level < 15:
            return "risk_on"
        else:
            return "mixed"
    
    def classify_volatility_regime(self, vix_level: float | None) -> VolatilityRegime:
        if vix_level is None:
            return "unknown"
        if vix_level < 15:
            return "calm"
        elif vix_level < 25:
            return "elevated"
        else:
            return "stressed"
```

### Step 5: World Model Integration

```python
# backend/src/hypertrade/world_model/collectors.py
from hypertrade.global_market.service import GlobalMarketService

class WorldModelCollectors:
    def collect_global_market(self) -> dict:
        """Collect cross-asset global market state."""
        service = GlobalMarketService()
        snapshot = service.get_snapshot()
        
        return {
            "risk_regime": snapshot.get("risk_regime", "unknown"),
            "volatility_regime": snapshot.get("volatility_regime", "unknown"),
            "dollar_pressure": snapshot.get("dollar_pressure", "unknown"),
            "rates_pressure": snapshot.get("rates_pressure", "unknown"),
            "cross_asset_signal": snapshot.get("cross_asset_signal", "unknown"),
            "tickers": snapshot.get("tickers", []),
            "missing_data": snapshot.get("missing_data", []),
            "source_refs": snapshot.get("source_refs", []),
            "as_of": snapshot.get("timestamp"),
        }
```

## Deliverables

1. **Code**
   - `backend/src/hypertrade/global_market/` module
   - yfinance and Alpha Vantage source adapters
   - Regime classification logic
   - World model collectors integration
   - API endpoints
   - Agent tool schema and executor

2. **Tests**
   - Unit tests for yfinance/Alpha Vantage adapters with mocked responses
   - Regime analyzer tests with fixture data
   - Integration tests for `GlobalMarketService`
   - World model snapshot tests verifying global market replacement
   - Agent planner test requiring `global_market_snapshot` for regime prompts

3. **Configuration**
   - `ALPHA_VANTAGE_API_KEY` optional env var
   - `GLOBAL_MARKET_ENABLED` flag (default true)
   - `GLOBAL_MARKET_CACHE_TTL_SECONDS` (default 300 = 5 minutes)

4. **Documentation**
   - Update `docs/architecture/22-world-model-development-roadmap.md`
   - Add `docs/knowledge/global-market-data-sources.md`
   - Update `README.md` with free data source setup

## Done Means

- World model `global_market` section shows live regime state, not fixture
- `GET /api/global-market/snapshot` returns current S&P 500, VIX, DXY, 10Y yield
- yfinance works without API key for all 9 tickers
- Alpha Vantage fallback activates on yfinance errors or rate limits
- `missing_data` correctly lists unavailable tickers
- Regime classification produces non-"unknown" values when data is available
- Agent prompt `全球市场现在是什么状态` calls `world_model_snapshot` and
  renders global market regime with source references
- Tests pass with mocked yfinance/Alpha Vantage responses

## Verification

### Focused Tests
```bash
uv run pytest tests/test_global_market_sources.py -q
uv run pytest tests/test_global_market_service.py -q
uv run pytest tests/test_world_model_snapshot.py -q
uv run pytest tests/test_agent_planner.py::test_global_market_routing -q
```

### Full Check
```bash
./scripts/check.sh
```

### Manual Smoke
```bash
# Test yfinance adapter directly
uv run python -c "
from hypertrade.global_market.sources.yfinance_source import YFinanceSource
source = YFinanceSource()
print(source.get_ticker('^GSPC'))
print(source.get_ticker('^VIX'))
"

# Test API endpoint
curl http://localhost:3334/api/global-market/snapshot | jq .

# Test Agent tool
uv run hypertrade ask "全球市场现在是什么状态"
```

## Dependencies

### Python Packages (add to pyproject.toml)
```toml
[project.dependencies]
yfinance = "^0.2.48"  # Free, no API key
requests = "^2.32.3"  # For Alpha Vantage
```

### Optional Environment Variables
```bash
# Optional: Alpha Vantage fallback (free tier: 25 requests/day)
# Get free key at: https://www.alphavantage.co/support/#api-key
ALPHA_VANTAGE_API_KEY=your_free_key_here

# Feature flag (default true)
GLOBAL_MARKET_ENABLED=true

# Cache TTL in seconds (default 300 = 5 minutes)
GLOBAL_MARKET_CACHE_TTL_SECONDS=300
```

## Risk Mitigation

1. **Rate Limits**
   - yfinance: no documented limit, but add retry with exponential backoff
   - Alpha Vantage free tier: 25 requests/day → cache responses for 5 minutes
   - If both fail, return `unknown` regime with explicit `missing_data`

2. **Market Hours**
   - US markets closed: yfinance returns last close
   - Document that regime state uses last available data, not real-time streaming

3. **Data Quality**
   - Validate price > 0, change_pct within [-20%, +20%] for sanity
   - Log but don't fail on unexpected ticker responses
   - World model must not invent data when sources fail

4. **Backward Compatibility**
   - World model continues working if global market is disabled
   - Fixture fallback remains for testing without internet

## Future Enhancements (Out of Scope for Sprint 75)

- Asia market data: Hong Kong HSI, China CSI 300
- Real-time streaming via WebSocket (paid sources)
- Historical regime state persistence for backtesting
- Custom technical indicators (moving averages, RSI)
- Alternative free sources: Yahoo Finance RSS, FRED API for rates

## References

- TradingAgents implementation: `/Users/jie.feng/Dev/Github/Private/TradingAgents/tradingagents/dataflows/`
- yfinance docs: https://github.com/ranaroussi/yfinance
- Alpha Vantage free API: https://www.alphavantage.co/documentation/
- HyperTrade world model roadmap: `docs/architecture/22-world-model-development-roadmap.md`
