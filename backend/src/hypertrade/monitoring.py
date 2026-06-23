from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import desc, select

from hypertrade.bitpro.mcp import LIVE_MUTATION_TOOLS, RESEARCH_MUTATION_TOOLS
from hypertrade.bitpro.paper_monitor import BitProPaperMonitorService
from hypertrade.db import (
    Database,
    MonitorAlertEvent,
    MonitorDefinition,
    MonitorRun,
    utc_now,
)
from hypertrade.strategy.library import StrategyLibraryService

LOGGER = logging.getLogger(__name__)

DEFAULT_MONITORS: tuple[dict[str, Any], ...] = (
    {
        "id": "mon_bitpro_paper_all",
        "name": "BitPro paper monitor",
        "monitor_type": "bitpro_paper",
        "scope": {"strategy_id": None, "event_limit": 50, "equity_sample_limit": 50},
        "thresholds": {
            "max_drawdown_pct": "10",
            "error_count": 1,
            "equity_drop": "0",
            "pnl_drop_pct": "1",
            "missing_data": True,
        },
        "schedule": {"mode": "manual"},
        "notification": {"sink": "log"},
    },
    {
        "id": "mon_strategy_library_freshness",
        "name": "Strategy library evidence freshness",
        "monitor_type": "strategy_library_freshness",
        "scope": {"query": "", "limit": 20},
        "thresholds": {"max_age_hours": 168, "missing_data": True},
        "schedule": {"mode": "manual"},
        "notification": {"sink": "log"},
    },
    {
        "id": "mon_connector_health",
        "name": "Connector health monitor",
        "monitor_type": "connector_health",
        "scope": {"connector": "bitpro_mcp"},
        "thresholds": {"missing_data": True},
        "schedule": {"mode": "manual"},
        "notification": {"sink": "log"},
    },
)
_DEFAULT_MONITOR_IDS = {str(definition["id"]) for definition in DEFAULT_MONITORS}

WRITE_TOOL_NAMES = RESEARCH_MUTATION_TOOLS | LIVE_MUTATION_TOOLS


class MonitorBitProAdapter(Protocol):
    def health(self) -> dict[str, Any]:
        """Read connector health."""
        ...

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


class NotificationSink(Protocol):
    def notify(self, alert: dict[str, Any]) -> None:
        """Deliver or record an alert."""
        ...


class LogNotificationSink:
    def notify(self, alert: dict[str, Any]) -> None:
        LOGGER.warning(
            "monitor alert code=%s level=%s monitor_id=%s run_id=%s message=%s",
            alert.get("code"),
            alert.get("level"),
            alert.get("monitor_id"),
            alert.get("run_id"),
            alert.get("message"),
        )


class MonitorService:
    def __init__(
        self,
        db: Database,
        *,
        bitpro_adapter: MonitorBitProAdapter | None = None,
        notification_sink: NotificationSink | None = None,
    ) -> None:
        self.db = db
        self.bitpro_adapter = bitpro_adapter
        self.notification_sink = notification_sink or LogNotificationSink()

    def ensure_default_monitors(self) -> None:
        for definition in DEFAULT_MONITORS:
            self.upsert_monitor(
                monitor_id=str(definition["id"]),
                name=str(definition["name"]),
                monitor_type=str(definition["monitor_type"]),
                scope=dict(definition["scope"]),
                thresholds=dict(definition["thresholds"]),
                schedule=dict(definition["schedule"]),
                notification=dict(definition["notification"]),
            )

    def upsert_monitor(
        self,
        *,
        monitor_id: str,
        name: str,
        monitor_type: str,
        scope: dict[str, Any] | None = None,
        thresholds: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
        notification: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        with self.db.session() as session:
            row = session.get(MonitorDefinition, monitor_id)
            if row is None:
                row = MonitorDefinition(id=monitor_id, name=name, monitor_type=monitor_type)
                session.add(row)
            row.name = name
            row.monitor_type = monitor_type
            row.enabled = enabled
            row.scope_json = dict(scope or {})
            row.thresholds_json = dict(thresholds or {})
            row.schedule_json = dict(schedule or {"mode": "manual"})
            row.notification_json = dict(notification or {"sink": "log"})
            session.flush()
            return _definition_to_dict(row, last_run=None)

    def list_monitors(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        self.ensure_default_monitors()
        with self.db.session() as session:
            statement = select(MonitorDefinition).order_by(MonitorDefinition.id)
            if not include_disabled:
                statement = statement.where(MonitorDefinition.enabled.is_(True))
            definitions = session.scalars(statement).all()
            results: list[dict[str, Any]] = []
            for definition in definitions:
                last_run = session.scalars(
                    select(MonitorRun)
                    .where(MonitorRun.monitor_id == definition.id)
                    .order_by(desc(MonitorRun.created_at))
                    .limit(1)
                ).first()
                results.append(_definition_to_dict(definition, last_run=last_run))
            return results

    def list_alerts(self, *, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self.db.session() as session:
            rows = session.scalars(
                select(MonitorAlertEvent)
                .order_by(desc(MonitorAlertEvent.created_at))
                .limit(safe_limit)
            ).all()
            return [_alert_row_to_dict(row) for row in rows]

    def run_monitor(self, monitor_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            definition = session.get(MonitorDefinition, monitor_id)
            if definition is None and monitor_id in _DEFAULT_MONITOR_IDS:
                self.ensure_default_monitors()
                definition = session.get(MonitorDefinition, monitor_id)
            if definition is None:
                raise KeyError(monitor_id)
            if not definition.enabled:
                raise ValueError(f"monitor disabled: {monitor_id}")
            previous_run = session.scalars(
                select(MonitorRun)
                .where(MonitorRun.monitor_id == monitor_id)
                .where(MonitorRun.status == "completed")
                .order_by(desc(MonitorRun.created_at))
                .limit(1)
            ).first()
            definition_payload = _definition_to_dict(definition, last_run=previous_run)

        result = self._collect(definition_payload)
        previous_metrics = _dict_or_empty(
            previous_run.metric_snapshot_json if previous_run is not None else None
        )
        metrics = _dict_or_empty(result.get("metric_snapshot"))
        drift = _metric_drift(previous_metrics, metrics)
        data_gaps = _dedupe_strings(result.get("data_gaps", []))
        alerts = _threshold_alerts(
            monitor_id=monitor_id,
            run_id="",
            monitor_type=str(definition_payload["monitor_type"]),
            thresholds=_dict_or_empty(definition_payload.get("thresholds")),
            metrics=metrics,
            drift=drift,
            data_gaps=data_gaps,
        )
        source_tools = _tool_calls(result.get("source_tools"))
        write_tools = _write_tool_calls(source_tools)
        if write_tools:
            alerts.append(
                {
                    "level": "critical",
                    "code": "monitor_write_tool_blocked",
                    "message": "Monitor collector attempted a write tool.",
                    "source_id": "",
                    "threshold": {"forbidden_tools": sorted(WRITE_TOOL_NAMES)},
                    "metric": {"tools": write_tools},
                }
            )
        recommended_actions = _dedupe_strings(result.get("recommended_actions", []))

        with self.db.session() as session:
            run = MonitorRun(
                monitor_id=monitor_id,
                monitor_type=str(definition_payload["monitor_type"]),
                status="completed",
                previous_run_id=previous_run.id if previous_run is not None else None,
                completed_at=utc_now(),
                scope_json=_dict_or_empty(definition_payload.get("scope")),
                source_tools_json=source_tools,
                metric_snapshot_json=metrics,
                drift_json=drift,
                alerts_json=[],
                data_gaps_json=data_gaps,
                recommended_actions_json=recommended_actions,
                result_json=result,
            )
            session.add(run)
            session.flush()
            run_id = run.id
            for alert in alerts:
                alert["run_id"] = run_id
                alert["monitor_id"] = monitor_id
                alert["source_id"] = str(alert.get("source_id") or run_id)
                row = MonitorAlertEvent(
                    monitor_id=monitor_id,
                    run_id=run_id,
                    level=str(alert.get("level", "warning")),
                    code=str(alert.get("code", "monitor_alert")),
                    message=str(alert.get("message", "")),
                    source_id=str(alert.get("source_id", run_id)),
                    threshold_json=_dict_or_empty(alert.get("threshold")),
                    metric_json=_dict_or_empty(alert.get("metric")),
                )
                session.add(row)
                session.flush()
                alert["id"] = row.id
                alert["created_at"] = row.created_at.isoformat()
                self.notification_sink.notify(alert)
            run.alerts_json = alerts
            session.flush()
            payload = _run_to_dict(run)

        return payload

    def _collect(self, definition: dict[str, Any]) -> dict[str, Any]:
        monitor_type = str(definition.get("monitor_type", ""))
        if monitor_type == "bitpro_paper":
            return self._run_bitpro_paper_monitor(definition)
        if monitor_type == "strategy_library_freshness":
            return self._run_strategy_library_monitor(definition)
        if monitor_type == "connector_health":
            return self._run_connector_health_monitor(definition)
        raise ValueError(f"unknown monitor type: {monitor_type}")

    def _run_bitpro_paper_monitor(self, definition: dict[str, Any]) -> dict[str, Any]:
        if self.bitpro_adapter is None:
            return _missing_adapter_result("bitpro_mcp")
        scope = _dict_or_empty(definition.get("scope"))
        strategy_id = _optional_int(scope.get("strategy_id"))
        capture = BitProPaperMonitorService(
            self.db,
            bitpro_adapter=self.bitpro_adapter,
        ).capture(
            strategy_id=strategy_id,
            event_limit=_safe_int(scope.get("event_limit"), default=50),
            equity_sample_limit=_safe_int(scope.get("equity_sample_limit"), default=50),
        )
        drift = _dict_or_empty(capture.get("drift"))
        monitor_summary = _dict_or_empty(capture.get("monitor_summary"))
        raw_drift_gaps = drift.get("data_gaps")
        drift_gaps = list(raw_drift_gaps) if isinstance(raw_drift_gaps, list) else []
        raw_summary_gaps = monitor_summary.get("data_gaps")
        summary_gaps = list(raw_summary_gaps) if isinstance(raw_summary_gaps, list) else []
        recommended_actions = monitor_summary.get("recommended_actions")
        recommended_actions = recommended_actions if isinstance(recommended_actions, list) else []
        return {
            "source": "bitpro.paper_monitor_snapshot",
            "metric_snapshot": _dict_or_empty(capture.get("metrics")),
            "source_tools": _tool_calls(capture.get("tool_calls")),
            "data_gaps": _dedupe_strings([*drift_gaps, *summary_gaps]),
            "recommended_actions": _dedupe_strings(recommended_actions),
            "raw": capture,
        }

    def _run_strategy_library_monitor(self, definition: dict[str, Any]) -> dict[str, Any]:
        scope = _dict_or_empty(definition.get("scope"))
        payload = StrategyLibraryService(self.db).search(
            query=str(scope.get("query", "")),
            limit=_safe_int(scope.get("limit"), default=20),
        )
        latest_at = _latest_strategy_evidence_at(payload)
        metrics = {
            "strategy_count": len(payload.get("items", []))
            if isinstance(payload.get("items"), list)
            else 0,
            "memory_count": _safe_int(payload.get("memory_count"), default=0),
            "latest_evidence_at": latest_at,
        }
        data_gaps = []
        if not metrics["memory_count"]:
            data_gaps.append("missing strategy_knowledge")
        return {
            "source": "memory.strategy_knowledge",
            "metric_snapshot": {key: value for key, value in metrics.items() if value is not None},
            "source_tools": [
                {
                    "tool": "strategy_library_search",
                    "status": "success",
                    "parameters": {
                        "query": scope.get("query", ""),
                        "limit": scope.get("limit", 20),
                    },
                }
            ],
            "data_gaps": data_gaps,
            "recommended_actions": ["Review strategy knowledge freshness before new experiments."],
            "raw": payload,
        }

    def _run_connector_health_monitor(self, definition: dict[str, Any]) -> dict[str, Any]:
        scope = _dict_or_empty(definition.get("scope"))
        connector = str(scope.get("connector", "bitpro_mcp"))
        if connector != "bitpro_mcp":
            return _missing_adapter_result(connector)
        if self.bitpro_adapter is None:
            return _missing_adapter_result(connector)
        payload = self.bitpro_adapter.health()
        health = _dict_or_empty(payload.get("health"))
        status = str(health.get("status") or payload.get("status") or "unknown")
        data_gaps = [] if status.lower() in {"ok", "healthy"} else [f"{connector} health={status}"]
        return {
            "source": connector,
            "metric_snapshot": {
                "connector": connector,
                "health_status": status,
                "contract_version": payload.get("contract_version", ""),
            },
            "source_tools": _tool_calls(payload.get("tool_calls")),
            "data_gaps": data_gaps,
            "recommended_actions": ["Check connector credentials and upstream health."],
            "raw": payload,
        }


def _definition_to_dict(
    definition: MonitorDefinition,
    *,
    last_run: MonitorRun | None,
) -> dict[str, Any]:
    return {
        "id": definition.id,
        "name": definition.name,
        "monitor_type": definition.monitor_type,
        "enabled": definition.enabled,
        "scope": definition.scope_json,
        "thresholds": definition.thresholds_json,
        "schedule": definition.schedule_json,
        "notification": definition.notification_json,
        "last_run_id": last_run.id if last_run is not None else None,
        "last_status": last_run.status if last_run is not None else None,
        "last_run_at": last_run.completed_at.isoformat()
        if last_run is not None and last_run.completed_at is not None
        else None,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


def _run_to_dict(run: MonitorRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "monitor_id": run.monitor_id,
        "monitor_type": run.monitor_type,
        "status": run.status,
        "previous_run_id": run.previous_run_id,
        "scope": run.scope_json,
        "source_tools": run.source_tools_json,
        "metric_snapshot": run.metric_snapshot_json,
        "drift": run.drift_json,
        "alerts": run.alerts_json,
        "data_gaps": run.data_gaps_json,
        "recommended_actions": run.recommended_actions_json,
        "result": run.result_json,
        "error": run.error,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _alert_row_to_dict(row: MonitorAlertEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "monitor_id": row.monitor_id,
        "run_id": row.run_id,
        "level": row.level,
        "code": row.code,
        "message": row.message,
        "source_id": row.source_id,
        "threshold": row.threshold_json,
        "metric": row.metric_json,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
    }


def _threshold_alerts(
    *,
    monitor_id: str,
    run_id: str,
    monitor_type: str,
    thresholds: dict[str, Any],
    metrics: dict[str, Any],
    drift: dict[str, Any],
    data_gaps: list[str],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    drawdown = _decimal_or_none(metrics.get("max_drawdown_pct"))
    max_drawdown = _decimal_or_none(thresholds.get("max_drawdown_pct"))
    if drawdown is not None and max_drawdown is not None and drawdown >= max_drawdown:
        alerts.append(
            _alert(
                monitor_id=monitor_id,
                run_id=run_id,
                code="drawdown_threshold_breached",
                message=f"max_drawdown_pct {drawdown} breached threshold {max_drawdown}",
                threshold={"max_drawdown_pct": str(max_drawdown)},
                metric={"max_drawdown_pct": str(drawdown)},
            )
        )

    error_count = _safe_int(metrics.get("error_count"), default=0)
    max_errors = _optional_int(thresholds.get("error_count"))
    if max_errors is not None and error_count >= max_errors:
        alerts.append(
            _alert(
                monitor_id=monitor_id,
                run_id=run_id,
                code="error_count_threshold_breached",
                message=f"error_count {error_count} breached threshold {max_errors}",
                threshold={"error_count": max_errors},
                metric={"error_count": error_count},
            )
        )

    equity_delta = _decimal_or_none(drift.get("equity_delta"))
    equity_drop = _decimal_or_none(thresholds.get("equity_drop"))
    if equity_delta is not None and equity_drop is not None and equity_delta <= -equity_drop:
        alerts.append(
            _alert(
                monitor_id=monitor_id,
                run_id=run_id,
                code="equity_drop_threshold_breached",
                message=f"latest_equity changed by {equity_delta}, threshold -{equity_drop}",
                threshold={"equity_drop": str(equity_drop)},
                metric={"equity_delta": str(equity_delta)},
            )
        )

    pnl_delta = _decimal_or_none(drift.get("total_pnl_delta_pct"))
    pnl_drop = _decimal_or_none(thresholds.get("pnl_drop_pct"))
    if pnl_delta is not None and pnl_drop is not None and pnl_delta <= -pnl_drop:
        alerts.append(
            _alert(
                monitor_id=monitor_id,
                run_id=run_id,
                code="pnl_drop_threshold_breached",
                message=f"total_pnl_pct changed by {pnl_delta}, threshold -{pnl_drop}",
                threshold={"pnl_drop_pct": str(pnl_drop)},
                metric={"total_pnl_delta_pct": str(pnl_delta)},
            )
        )

    max_age_hours = _decimal_or_none(thresholds.get("max_age_hours"))
    latest_evidence_at = _parse_datetime(metrics.get("latest_evidence_at"))
    if max_age_hours is not None and latest_evidence_at is not None:
        age_hours = Decimal(str((utc_now() - latest_evidence_at).total_seconds() / 3600))
        if age_hours > max_age_hours:
            alerts.append(
                _alert(
                    monitor_id=monitor_id,
                    run_id=run_id,
                    code="strategy_evidence_stale",
                    message=f"latest strategy evidence age {age_hours:.2f}h exceeded threshold",
                    threshold={"max_age_hours": str(max_age_hours)},
                    metric={"age_hours": f"{age_hours:.2f}"},
                )
            )

    if thresholds.get("missing_data") and data_gaps:
        alerts.append(
            _alert(
                monitor_id=monitor_id,
                run_id=run_id,
                code="monitor_data_gap",
                message=f"{monitor_type} reported data gaps: {', '.join(data_gaps[:3])}",
                threshold={"missing_data": True},
                metric={"data_gaps": data_gaps},
            )
        )

    if monitor_type == "connector_health":
        health_status = str(metrics.get("health_status", "")).lower()
        if health_status and health_status not in {"ok", "healthy"}:
            alerts.append(
                _alert(
                    monitor_id=monitor_id,
                    run_id=run_id,
                    code="connector_health_degraded",
                    message=f"connector health is {health_status}",
                    threshold={"health_status": "ok"},
                    metric={"health_status": health_status},
                )
            )
    return alerts


def _alert(
    *,
    monitor_id: str,
    run_id: str,
    code: str,
    message: str,
    threshold: dict[str, Any],
    metric: dict[str, Any],
    level: str = "warning",
) -> dict[str, Any]:
    return {
        "monitor_id": monitor_id,
        "run_id": run_id,
        "level": level,
        "code": code,
        "message": message,
        "source_id": run_id,
        "threshold": threshold,
        "metric": metric,
    }


def _metric_drift(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    if not previous:
        return {"mode": "baseline", "alerts": [], "data_gaps": _metric_gaps(current)}
    error_count_delta = _safe_int(current.get("error_count"), default=0) - _safe_int(
        previous.get("error_count"),
        default=0,
    )
    return {
        "mode": "compared",
        "equity_delta": _delta_text(previous.get("latest_equity"), current.get("latest_equity")),
        "total_pnl_delta_pct": _delta_text(
            previous.get("total_pnl_pct"),
            current.get("total_pnl_pct"),
        ),
        "max_drawdown_delta_pct": _delta_text(
            previous.get("max_drawdown_pct"),
            current.get("max_drawdown_pct"),
        ),
        "error_count_delta": error_count_delta,
        "data_gaps": _metric_gaps(current),
    }


def _metric_gaps(metrics: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for key in ("latest_equity", "total_pnl_pct", "max_drawdown_pct"):
        if key in metrics and metrics.get(key) is None or key not in metrics:
            gaps.append(f"missing {key}")
    return gaps


def _latest_strategy_evidence_at(payload: dict[str, Any]) -> str | None:
    latest_values: list[str] = []
    items = payload.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        latest = item.get("latest")
        if isinstance(latest, dict):
            created_at = latest.get("created_at")
            if created_at:
                latest_values.append(str(created_at))
    return max(latest_values) if latest_values else None


def _missing_adapter_result(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "metric_snapshot": {"connector": source, "health_status": "missing_adapter"},
        "source_tools": [],
        "data_gaps": [f"missing {source} adapter"],
        "recommended_actions": ["Configure the connector adapter before running this monitor."],
        "raw": {},
    }


def _write_tool_calls(source_tools: list[dict[str, Any]]) -> list[str]:
    names = []
    for call in source_tools:
        name = str(call.get("tool") or call.get("tool_name") or "")
        if name in WRITE_TOOL_NAMES:
            names.append(name)
    return names


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(call) for call in value if isinstance(call, dict)]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _dedupe_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    results: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        results.append(text)
    return results


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace("%", ""))
    except Exception:
        return None


def _delta_text(previous: Any, current: Any) -> str | None:
    previous_decimal = _decimal_or_none(previous)
    current_decimal = _decimal_or_none(current)
    if previous_decimal is None or current_decimal is None:
        return None
    return _decimal_text(current_decimal - previous_decimal)


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=utc_now().tzinfo)
    return parsed
