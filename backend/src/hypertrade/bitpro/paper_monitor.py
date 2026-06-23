from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import desc, select

from hypertrade.db import BitProPaperMonitorSnapshot, Database


class BitProPaperMonitorAdapter(Protocol):
    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        """Read BitPro paper dashboard state."""
        ...

    def paper_events(
        self,
        *,
        strategy_id: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read BitPro paper event stream."""
        ...

    def paper_equity_curve(
        self,
        *,
        strategy_id: int | None = None,
        sample_limit: int = 50,
    ) -> dict[str, Any]:
        """Read BitPro paper equity curve."""
        ...


class BitProPaperMonitorService:
    def __init__(self, db: Database, *, bitpro_adapter: BitProPaperMonitorAdapter) -> None:
        self.db = db
        self.bitpro_adapter = bitpro_adapter

    def capture(
        self,
        *,
        strategy_id: int | None = None,
        event_limit: int = 50,
        equity_sample_limit: int = 50,
    ) -> dict[str, Any]:
        dashboard = self.bitpro_adapter.paper_dashboard(strategy_id=strategy_id)
        events = self.bitpro_adapter.paper_events(strategy_id=strategy_id, limit=event_limit)
        equity = self.bitpro_adapter.paper_equity_curve(
            strategy_id=strategy_id,
            sample_limit=equity_sample_limit,
        )

        monitor_summary = _dict_or_empty(dashboard.get("monitor_summary"))
        event_summary = _dict_or_empty(events.get("event_summary"))
        equity_summary = _dict_or_empty(equity.get("equity_summary"))
        resolved_strategy_id = _resolve_strategy_id(strategy_id, dashboard, monitor_summary)
        scope_key = str(resolved_strategy_id) if resolved_strategy_id is not None else "all"
        metrics = _snapshot_metrics(
            strategy_id=resolved_strategy_id,
            monitor_summary=monitor_summary,
            event_summary=event_summary,
            equity_summary=equity_summary,
        )

        with self.db.session() as session:
            previous = session.scalars(
                select(BitProPaperMonitorSnapshot)
                .where(BitProPaperMonitorSnapshot.scope_key == scope_key)
                .order_by(desc(BitProPaperMonitorSnapshot.created_at))
                .limit(1)
            ).first()
            drift = _snapshot_drift(
                previous.metrics_json if previous is not None else None,
                metrics,
            )
            tool_calls = [
                *_tool_calls(dashboard),
                *_tool_calls(events),
                *_tool_calls(equity),
            ]
            row = BitProPaperMonitorSnapshot(
                scope_key=scope_key,
                strategy_id=resolved_strategy_id,
                previous_snapshot_id=previous.id if previous is not None else None,
                status="completed",
                dashboard_json=_dict_or_empty(dashboard.get("dashboard")),
                running_strategies_json=_dict_or_empty(dashboard.get("running_strategies")),
                monitor_summary_json=monitor_summary,
                event_summary_json=event_summary,
                equity_summary_json=equity_summary,
                metrics_json=metrics,
                drift_json=drift,
                tool_calls_json=tool_calls,
            )
            session.add(row)
            session.flush()
            snapshot_id = row.id
            previous_snapshot_id = row.previous_snapshot_id

        return {
            "status": "ok",
            "contract_version": str(dashboard.get("contract_version", "bitpro-mcp-v1")),
            "snapshot_id": snapshot_id,
            "previous_snapshot_id": previous_snapshot_id,
            "scope_key": scope_key,
            "strategy_id": resolved_strategy_id,
            "metrics": metrics,
            "drift": drift,
            "event_summary": event_summary,
            "equity_summary": equity_summary,
            "monitor_summary": monitor_summary,
            "tool_calls": tool_calls,
        }


def _resolve_strategy_id(
    requested_strategy_id: int | None,
    dashboard: dict[str, Any],
    monitor_summary: dict[str, Any],
) -> int | None:
    if requested_strategy_id is not None:
        return int(requested_strategy_id)
    current_dashboard = _dict_or_empty(monitor_summary.get("current_dashboard"))
    candidate = current_dashboard.get("strategy_id")
    if candidate is None:
        system = _dict_or_empty(_dict_or_empty(dashboard.get("dashboard")).get("system"))
        candidate = system.get("strategy_id")
    try:
        return int(candidate) if candidate is not None else None
    except (TypeError, ValueError):
        return None


def _snapshot_metrics(
    *,
    strategy_id: int | None,
    monitor_summary: dict[str, Any],
    event_summary: dict[str, Any],
    equity_summary: dict[str, Any],
) -> dict[str, Any]:
    current = _dict_or_empty(monitor_summary.get("current_dashboard"))
    latest_equity = _decimal_text(
        _first_present(equity_summary.get("latest_equity"), current.get("equity"))
    )
    max_drawdown = _decimal_text(
        _first_present(
            equity_summary.get("max_drawdown_pct"),
            equity_summary.get("latest_drawdown_pct"),
            current.get("max_drawdown_pct"),
        )
    )
    metrics = {
        "strategy_id": strategy_id,
        "strategy_name": current.get("strategy_name"),
        "state": current.get("state"),
        "mode": current.get("mode"),
        "latest_equity": latest_equity,
        "total_pnl_pct": _decimal_text(current.get("total_pnl_pct")),
        "max_drawdown_pct": max_drawdown,
        "event_count": _int_or_zero(event_summary.get("count")),
        "error_count": _int_or_zero(event_summary.get("error_count")),
        "latest_event_at": event_summary.get("latest_event_at"),
        "equity_point_count": _int_or_zero(equity_summary.get("count")),
        "latest_equity_at": equity_summary.get("latest_at"),
    }
    return {key: value for key, value in metrics.items() if value is not None}


def _snapshot_drift(
    previous_metrics: dict[str, Any] | None,
    current_metrics: dict[str, Any],
) -> dict[str, Any]:
    gaps = _metric_gaps(current_metrics)
    if not previous_metrics:
        return {
            "mode": "baseline",
            "alerts": [],
            "data_gaps": gaps,
        }

    equity_delta = _delta_text(
        previous_metrics.get("latest_equity"),
        current_metrics.get("latest_equity"),
    )
    pnl_delta = _delta_text(
        previous_metrics.get("total_pnl_pct"),
        current_metrics.get("total_pnl_pct"),
    )
    drawdown_delta = _delta_text(
        previous_metrics.get("max_drawdown_pct"),
        current_metrics.get("max_drawdown_pct"),
    )
    error_count_delta = _int_or_zero(current_metrics.get("error_count")) - _int_or_zero(
        previous_metrics.get("error_count")
    )
    alerts = _drift_alerts(
        equity_delta=equity_delta,
        pnl_delta=pnl_delta,
        drawdown_delta=drawdown_delta,
        error_count_delta=error_count_delta,
    )
    return {
        "mode": "compared",
        "equity_delta": equity_delta,
        "total_pnl_delta_pct": pnl_delta,
        "max_drawdown_delta_pct": drawdown_delta,
        "error_count_delta": error_count_delta,
        "alerts": alerts,
        "data_gaps": gaps,
    }


def _drift_alerts(
    *,
    equity_delta: str | None,
    pnl_delta: str | None,
    drawdown_delta: str | None,
    error_count_delta: int,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    equity = _decimal_or_none(equity_delta)
    if equity is not None and equity < 0:
        alerts.append(
            {
                "level": "warning",
                "code": "equity_drop",
                "message": f"latest_equity dropped by {_decimal_text(equity)}",
            }
        )
    pnl = _decimal_or_none(pnl_delta)
    if pnl is not None and pnl <= Decimal("-1"):
        alerts.append(
            {
                "level": "warning",
                "code": "pnl_drop",
                "message": f"total_pnl_pct dropped by {_decimal_text(pnl)}%",
            }
        )
    drawdown = _decimal_or_none(drawdown_delta)
    if drawdown is not None and drawdown >= Decimal("2"):
        alerts.append(
            {
                "level": "warning",
                "code": "drawdown_expanded",
                "message": f"max_drawdown_pct increased by {_decimal_text(drawdown)}%",
            }
        )
    if error_count_delta > 0:
        alerts.append(
            {
                "level": "warning",
                "code": "new_event_errors",
                "message": f"paper error count increased by {error_count_delta}",
            }
        )
    return alerts


def _metric_gaps(metrics: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for key in ("latest_equity", "total_pnl_pct", "max_drawdown_pct"):
        if metrics.get(key) is None:
            gaps.append(f"missing {key}")
    return gaps


def _tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    calls = payload.get("tool_calls", [])
    if not isinstance(calls, list):
        return []
    return [call for call in calls if isinstance(call, dict)]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace("%", ""))
    except Exception:
        return None


def _decimal_text(value: Any) -> str | None:
    decimal = _decimal_or_none(value)
    if decimal is None:
        return None
    text = format(decimal.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _delta_text(previous: Any, current: Any) -> str | None:
    previous_decimal = _decimal_or_none(previous)
    current_decimal = _decimal_or_none(current)
    if previous_decimal is None or current_decimal is None:
        return None
    return _decimal_text(current_decimal - previous_decimal)


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
