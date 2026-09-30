from datetime import UTC, datetime

from hypertrade.market.news import InMemoryNewsFeed, NewsArticle, NewsIngestionService
from hypertrade.market.sentiment import NewsSentimentAnalyzer


def test_news_article_creation_and_deduplication():
    now = datetime.now(UTC)
    art1 = NewsArticle.create(
        title="SEC Approves First Ethereum Spot ETF with Staking Option",
        content="The US SEC has unexpectedly approved spot ETH ETFs.",
        url="https://news.example.com/eth-etf",
        source="coindesk",
        published_at=now,
        symbols=["ETH"],
    )
    assert art1.id.startswith("news_")
    assert art1.symbols == ["ETH"]

    art2 = NewsArticle.create(
        title="SEC Approves First Ethereum Spot ETF with Staking Option",
        content="Different content but same title and url.",
        url="https://news.example.com/eth-etf",
        source="coindesk",
        published_at=now,
        symbols=["ETH", "BTC"],
    )
    assert art1.id == art2.id

    service = NewsIngestionService()
    added1 = service.ingest([art1])
    assert added1 == 1

    # Ingesting art2 merges symbols without duplicating
    added2 = service.ingest([art2])
    assert added2 == 0

    latest = service.get_latest(limit=10, symbol="ETH")
    assert len(latest) == 1
    assert "BTC" in latest[0].symbols


def test_news_ingestion_feed_and_search():
    feed = InMemoryNewsFeed()
    feed.add(
        NewsArticle.create(
            title="Major Protocol Exploit Results in 50M USDC Drained",
            content="Hackers exploited a smart contract vulnerability.",
            symbols=["USDC"],
        )
    )
    feed.add(
        NewsArticle.create(
            title="Bitcoin Breaks Above All-Time High As Inflows Surge",
            content="Massive institutional demand drives BTC to new records.",
            symbols=["BTC"],
        )
    )

    service = NewsIngestionService(sources=[feed])
    added = service.sync_sources()
    assert added == 2

    btc_news = service.get_latest(symbol="BTC")
    assert len(btc_news) == 1
    assert "Bitcoin" in btc_news[0].title

    search_res = service.search("Exploit")
    assert len(search_res) == 1
    assert "Exploit" in search_res[0].title


def test_news_sentiment_analysis_bullish():
    analyzer = NewsSentimentAnalyzer()
    art = NewsArticle.create(
        title="Bitcoin Surges as Inflows Rally to All-Time High",
        content="Massive accumulation by institutional funds sparks breakout.",
        symbols=["BTC"],
    )
    sentiment = analyzer.analyze(art)

    assert sentiment.sentiment_score > 0.3
    assert "BTC" in sentiment.affected_symbols
    assert sentiment.urgency in {"high", "breaking", "normal"}


def test_news_sentiment_analysis_bearish_and_urgent():
    analyzer = NewsSentimentAnalyzer()
    art = NewsArticle.create(
        title="Breaking: Major DeFi Protocol Hacked, Funds Stolen in Exploit",
        content="Security researchers confirm protocol drained completely.",
        symbols=["ETH"],
    )
    sentiment = analyzer.analyze(art)

    assert sentiment.sentiment_score < -0.3
    assert sentiment.event_category == "exploit_hack"
    assert sentiment.urgency == "breaking"


def test_sentiment_aggregation_for_symbol():
    analyzer = NewsSentimentAnalyzer()
    articles = [
        NewsArticle.create(
            title="Solana Rallies as Ecosystem Inflows Surge",
            symbols=["SOL"],
        ),
        NewsArticle.create(
            title="Major Exchange Lists SOL-USDT Perpetual Contracts",
            symbols=["SOL"],
        ),
    ]
    sentiments = analyzer.analyze_batch(articles)
    aggregated = analyzer.aggregate_symbol_sentiment("SOL-USDT-SWAP", sentiments)

    assert aggregated["symbol"] == "SOL-USDT-SWAP"
    assert aggregated["sentiment_score"] > 0.2
    assert aggregated["label"] == "bullish"
    assert aggregated["sample_count"] == 2
