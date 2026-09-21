from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.evolution_diagnostics import sampling_status

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)
SNAPSHOT = {
    "instance_id": "paper-original",
    "strategy_id": 501,
    "strategy_version": "v1",
    "config_version": "c1",
    "session": {"started_at": "2026-09-01T00:00:00Z"},
}


class Client:
    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault

    def strategy_return_series(self, **kwargs):
        self.calls.append(kwargs)
        if self.fault == "cost":
            raise ValueError("cost model missing taker fee")
        points = [
            {"timestamp": (NOW - timedelta(hours=h)).isoformat(), "equity": "100"}
            for h in range(6, -1, -1)
        ]
        page = {
            "schema_version": "strategy_return_series.v1",
            "source_layer": "paper",
            "source_id": "paper-original",
            "strategy_id": 501,
            "strategy_version": "v1",
            "config_version": "c1",
            "currency": "USDT",
            "cost_model": {
                "fees": {"taker_fee_bps": 5},
                "slippage": {"slippage_bps": 2},
                "funding": {"mode": "net"},
            },
            "bucket_seconds": 3600,
            "timezone": "UTC",
            "source_hash": "source",
            "content_hash": "content",
            "pagination": {},
            "data_gaps": [],
            "points": points,
        }
        if self.fault == "stale":
            page["points"] = points[:3]
        elif self.fault == "gap":
            page["points"] = [points[0], *points[4:]]
        elif self.fault == "identity":
            page["source_id"] = "another-session"
        elif self.fault == "version":
            page["config_version"] = "changed"
        elif self.fault == "pagination":
            page["pagination"]["next_cursor"] = "more"
        elif self.fault == "empty":
            page["points"] = []
        elif self.fault == "nan":
            points[-1]["equity"] = "NaN"
        elif self.fault == "missing_cost":
            page["cost_model"] = {}
        return page


def test_current_sampling_is_independent_of_historical_readiness():
    client = Client()
    result = sampling_status(client, SNAPSHOT, NOW)
    assert result["state"] == "current"
    assert result["sample_count"] == 7
    assert result["latest_sample_at"] == NOW.isoformat()
    assert result["historical_window_verified"] is False
    assert len(client.calls) == 1
    assert client.calls[0]["source_id"] == SNAPSHOT["instance_id"]
    assert client.calls[0]["limit"] == 500


@pytest.mark.parametrize(
    "fault,state",
    [
        ("stale", "stale"),
        ("gap", "gaps"),
        ("identity", "unavailable"),
        ("version", "unavailable"),
        ("pagination", "unavailable"),
        ("empty", "unavailable"),
        ("nan", "unavailable"),
        ("cost", "unavailable"),
        ("missing_cost", "unavailable"),
    ],
)
def test_sampling_never_labels_invalid_or_old_evidence_current(fault, state):
    result = sampling_status(Client(fault), SNAPSHOT, NOW)
    assert result["state"] == state
    assert result["historical_window_verified"] is False


def test_legacy_session_gap_never_creates_or_guesses_a_session():
    client = Client()
    result = sampling_status(client, {"strategy_id": 296}, NOW)
    assert result["state"] == "unavailable"
    assert result["reason_code"] == "session_identity_missing"
    assert client.calls == []


def test_bounded_point_error_is_actionable_and_does_not_expose_raw_error():
    from hypertrade.arc.evolution_diagnostics import blocked_data_diagnostic
    from hypertrade.bitpro.mcp import BitProMcpError

    class TooMany(Client):
        def strategy_return_series(self, **kwargs):
            raise BitProMcpError(
                "paper source exceeds bounded point contract secret=do-not-copy", status_code=422
            )

    report = blocked_data_diagnostic(
        TooMany(), SNAPSHOT, NOW, "paper_session_younger_than_fourteen_days"
    )
    sampling = report["data_readiness"]["sampling"]
    assert sampling["reason_code"] == "source_point_limit_exceeded"
    assert sampling["http_status"] == 422
    assert "采样点数" in report["reason"]
    assert "do-not-copy" not in str(report)
    assert "14天" in report["reason"]


def test_scan_reports_sampling_even_when_trades_block_research():
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService

    class Running(Client):
        def paper_strategy_performance(self, **kwargs):
            return {
                "strategies": [{"strategy_id": 501, "mode": "paper", "strategy_name": "source"}]
            }

        def paper_snapshot(self, **kwargs):
            return {**SNAPSHOT, "status": "running", "trade_count": 1}

    client = Running()
    diagnostics, chosen = EvolutionService(None, client)._scan(EvolutionConfig(), NOW)
    assert chosen is None
    assert diagnostics[0]["status"] == "unavailable"
    assert diagnostics[0]["data_readiness"]["blocking_reason"] == "成交样本不足"
    assert diagnostics[0]["data_readiness"]["sampling"]["state"] == "current"
    assert "采样正常" in diagnostics[0]["reason"]
    assert len(client.calls) == 1


def test_scan_preserves_legacy_session_and_makes_no_sampling_request():
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService

    class Legacy(Client):
        def paper_strategy_performance(self, **kwargs):
            return {"strategies": [{"strategy_id": 296, "mode": "paper"}]}

        def paper_snapshot(self, **kwargs):
            raise ValueError("该策略尚未通过 paper_configure 创建纸面会话")

    client = Legacy()
    diagnostics, chosen = EvolutionService(None, client)._scan(EvolutionConfig(), NOW)
    assert chosen is None
    assert diagnostics[0]["data_readiness"]["sampling"]["reason_code"] == "session_identity_missing"
    assert "不重建" in diagnostics[0]["data_readiness"]["next_action"]
    assert client.calls == []
