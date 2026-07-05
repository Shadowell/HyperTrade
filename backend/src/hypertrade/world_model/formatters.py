"""Formatters for world model snapshot output."""

from __future__ import annotations

from typing import Any


def format_global_market(gm: dict[str, Any]) -> str:
    """Format global market data for readable output.

    Args:
        gm: Global market data dict

    Returns:
        Formatted string
    """
    lines = []
    lines.append("=" * 70)
    lines.append("🌍 全球市场状态 (Global Market)")
    lines.append("=" * 70)

    # Status
    status_emoji = {"healthy": "✅", "degraded": "⚠️", "unknown": "❓"}
    status = gm.get("status", "unknown")
    lines.append(f"\n状态: {status_emoji.get(status, '')} {status}")

    # Regime classifications
    lines.append("\n【市场制度分类】")

    regime_map = {
        "risk_on": "✅ 风险偏好 (Risk-On)",
        "risk_off": "⚠️  风险厌恶 (Risk-Off)",
        "stress": "🚨 极端压力 (Stress)",
        "mixed": "⚖️  信号混合 (Mixed)",
        "unknown": "❓ 未知",
    }

    volatility_map = {
        "calm": "😌 平静 (VIX<15)",
        "elevated": "⬆️  偏高 (VIX 15-25)",
        "stressed": "🔥 极端 (VIX>25)",
        "unknown": "❓ 未知",
    }

    cross_asset_map = {
        "supportive": "✅ 共振",
        "conflicting": "⚡ 矛盾",
        "hostile": "🚨 对立",
        "unknown": "❓ 未知",
    }

    risk_regime = gm.get("risk_regime", "unknown")
    volatility = gm.get("volatility_regime", "unknown")
    dollar = gm.get("dollar_pressure", "unknown")
    rates = gm.get("rates_pressure", "unknown")
    cross_asset = gm.get("cross_asset_signal", "unknown")

    lines.append(f"  风险制度: {regime_map.get(risk_regime, risk_regime)}")
    lines.append(f"  波动率:   {volatility_map.get(volatility, volatility)}")
    lines.append(f"  美元压力: {dollar}")
    lines.append(f"  利率压力: {rates}")
    lines.append(f"  跨资产:   {cross_asset_map.get(cross_asset, cross_asset)}")

    # Key tickers
    tickers = gm.get("tickers", [])
    if tickers:
        lines.append("\n【关键市场数据】")

        # Group by region
        us = [
            t for t in tickers if t["symbol"] in ["^GSPC", "^IXIC", "^RUT"] and not t.get("error")
        ]
        asia = [
            t
            for t in tickers
            if t["symbol"] in ["^HSI", "^N225", "000001.SS", "^KS11"] and not t.get("error")
        ]
        europe = [
            t for t in tickers if t["symbol"] in ["^STOXX50E", "^FTSE"] and not t.get("error")
        ]

        ticker_names = {
            "^GSPC": "标普500",
            "^IXIC": "纳指",
            "^RUT": "罗素2000",
            "^HSI": "恒指",
            "^N225": "日经",
            "000001.SS": "上证",
            "^KS11": "韩国",
            "^STOXX50E": "欧50",
            "^FTSE": "英国",
            "^VIX": "VIX",
        }

        if us:
            lines.append("  美国:")
            for t in us[:3]:
                name = ticker_names.get(t["symbol"], t["symbol"])
                chg = t.get("change_pct", 0)
                emoji = "📈" if chg > 0 else "📉" if chg < 0 else "➖"
                lines.append(f"    {emoji} {name:8s} {t.get('price', 0):8.1f} ({chg:+.2f}%)")

        if asia:
            lines.append("  亚洲:")
            for t in asia[:4]:
                name = ticker_names.get(t["symbol"], t["symbol"])
                chg = t.get("change_pct", 0)
                emoji = "📈" if chg > 0 else "📉" if chg < 0 else "➖"
                lines.append(f"    {emoji} {name:8s} {t.get('price', 0):8.1f} ({chg:+.2f}%)")

        if europe:
            lines.append("  欧洲:")
            for t in europe[:2]:
                name = ticker_names.get(t["symbol"], t["symbol"])
                chg = t.get("change_pct", 0)
                emoji = "📈" if chg > 0 else "📉" if chg < 0 else "➖"
                lines.append(f"    {emoji} {name:8s} {t.get('price', 0):8.1f} ({chg:+.2f}%)")

        # VIX
        vix_ticker = next(
            (t for t in tickers if t["symbol"] == "^VIX" and not t.get("error")), None
        )
        if vix_ticker:
            vix_val = vix_ticker.get("price", 0)
            vix_status = "😌平静" if vix_val < 15 else "😐偏高" if vix_val < 25 else "😱极端"
            lines.append(f"  恐慌指数: VIX {vix_val:.1f} ({vix_status})")

    # Timestamp
    as_of = gm.get("as_of", "")
    if as_of:
        lines.append(f"\n数据时间: {as_of[:19]}")

    lines.append("=" * 70)

    return "\n".join(lines)


def format_world_model_snapshot(snapshot: dict[str, Any]) -> str:
    """Format world model snapshot for readable CLI output.

    Args:
        snapshot: World model snapshot dict

    Returns:
        Formatted string for CLI display
    """
    lines = []

    # Header
    lines.append("\n" + "=" * 70)
    lines.append("🌐 HyperTrade 世界模型快照 (World Model Snapshot)")
    lines.append("=" * 70)

    # 1. Global Market (most important)
    if "global_market" in snapshot:
        lines.append("\n" + format_global_market(snapshot["global_market"]))

    # 2. Crypto Market Summary
    if "crypto_market" in snapshot:
        cm = snapshot["crypto_market"]
        lines.append("\n" + "=" * 70)
        lines.append("💰 加密货币市场 (Crypto Market)")
        lines.append("=" * 70)

        status_emoji = {"available": "✅", "stale": "⚠️", "unavailable": "❌"}
        status = cm.get("status", "unknown")
        lines.append(f"\n状态: {status_emoji.get(status, '')} {status}")

        ticker_count = cm.get("ticker_count", 0)
        lines.append(f"股票数量: {ticker_count} 个")

        if "top_movers" in cm:
            movers = cm["top_movers"][:5]
            if movers:
                lines.append("\n【涨跌幅前5】")
                for m in movers:
                    symbol = m.get("symbol", "")
                    chg = m.get("change_24h", 0)
                    price = m.get("last_price", 0)
                    emoji = "📈" if chg > 0 else "📉"
                    lines.append(f"  {emoji} {symbol:12s} ${price:10.2f} ({chg:+6.2f}%)")

    # 3. Strategy Status
    if "strategy_memory" in snapshot:
        sm = snapshot["strategy_memory"]
        lines.append("\n" + "=" * 70)
        lines.append("📊 策略状态 (Strategy)")
        lines.append("=" * 70)

        status_emoji = {"healthy": "✅", "stale": "⚠️", "unavailable": "❌"}
        status = sm.get("status", "unknown")
        lines.append(f"\n状态: {status_emoji.get(status, '')} {status}")
        lines.append(f"策略记忆: {sm.get('memory_count', 0)} 条")

    # 4. Execution Status
    if "execution" in snapshot:
        ex = snapshot["execution"]
        lines.append("\n" + "=" * 70)
        lines.append("⚡ 执行状态 (Execution)")
        lines.append("=" * 70)

        status_emoji = {"healthy": "✅", "watch": "⚠️", "unavailable": "❌"}
        status = ex.get("status", "unknown")
        lines.append(f"\n状态: {status_emoji.get(status, '')} {status}")
        lines.append(f"持仓数: {ex.get('open_position_count', 0)} 个")
        lines.append(f"成交数: {ex.get('recent_fill_count', 0)} 笔")

    # 5. Decision
    if "decision" in snapshot:
        decision = snapshot["decision"]
        lines.append("\n" + "=" * 70)
        lines.append("🎯 推荐行动 (Decision)")
        lines.append("=" * 70)

        selected_action = decision.get("selected_action_id", "none")
        score = decision.get("selected_score", 0)
        policy = decision.get("policy_status", "unknown")

        action_emoji = {
            "observe_more": "👀",
            "run_monitor": "🔍",
            "inspect_trace": "🔎",
            "hold": "⏸️",
            "pause_strategy_request": "⏯️",
        }

        lines.append(f"\n推荐: {action_emoji.get(selected_action, '⚡')} {selected_action}")
        lines.append(f"评分: {score:.1f}")
        lines.append(f"策略: {policy}")

        needs_confirm = decision.get("human_confirmation_required", False)
        if needs_confirm:
            lines.append("⚠️  需要人工确认")

    # 6. Portfolio
    if "portfolio" in snapshot:
        portfolio = snapshot["portfolio"]
        lines.append("\n" + "=" * 70)
        lines.append("💼 投资组合 (Portfolio)")
        lines.append("=" * 70)

        if "recommendations" in portfolio and portfolio["recommendations"]:
            rec = portfolio["recommendations"][0]
            rec_type = rec.get("recommendation_type", "")
            rec_score = rec.get("score", 0)
            lines.append(f"\n推荐: {rec_type}")
            lines.append(f"评分: {rec_score:.1f}")

    # Footer
    lines.append("\n" + "=" * 70)
    lines.append("数据成本: $0/月 | 完全免费")
    lines.append("=" * 70 + "\n")

    return "\n".join(lines)
