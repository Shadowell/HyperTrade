"""Paper provision must fail closed and must call configure + start."""

import hashlib
import json
from typing import Any

import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, PaperPreauthorizationV1
from hypertrade.arc.incubation import ARCPaperIncubationResolver, format_bitpro_strategy_name


def _validated(**spec: Any) -> ARCCandidateAttemptV1:
    return ARCCandidateAttemptV1(
        attempt_id="att_probe",
        candidate_id="cand_probe",
        state="validated",
        hypothesis="probe",
        strategy_code="class X(BaseStrategy):\n    pass\n",
        strategy_spec=spec,
    )


class _RecordingClient:
    def __init__(self, *, create: Any = None, configure: Any = None, start: Any = None) -> None:
        self.calls: list[str] = []
        self.kwargs: dict[str, dict[str, Any]] = {}
        self._create = (
            create
            if create is not None
            else {
                "status": "ok",
                "strategy": {"id": 42},
            }
        )
        self._configure = (
            configure
            if configure is not None
            else {
                "status": "ok",
                "paper": {"configured": True, "strategy_id": 42, "instance_id": "paper_9"},
            }
        )
        self._start = (
            start
            if start is not None
            else {
                "status": "ok",
                "paper": {"started": True, "strategy_id": 42, "instance_id": "paper_9"},
            }
        )

    def strategy_create(self, **kwargs: Any) -> Any:
        self.calls.append("strategy_create")
        self.kwargs["strategy_create"] = kwargs
        if isinstance(self._create, Exception):
            raise self._create
        return self._create

    def strategy_get(self, *, strategy_id: int) -> Any:
        self.calls.append("strategy_get")
        return {
            "status": "ok",
            "strategy": {
                "id": strategy_id,
                "script_content": _validated().strategy_code,
                "config": {},
                "status": "stopped",
            },
        }

    def paper_configure(self, **kwargs: Any) -> Any:
        self.calls.append("paper_configure")
        self.kwargs["paper_configure"] = kwargs
        if isinstance(self._configure, Exception):
            raise self._configure
        result = self._configure
        if isinstance(result, dict) and isinstance(result.get("paper"), dict):
            result["paper"].setdefault(
                "strategy_version",
                "sha256:"
                + hashlib.sha256(
                    json.dumps(
                        {"script_content": _validated().strategy_code},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            )
        return result

    def paper_start(self, **kwargs: Any) -> Any:
        self.calls.append("paper_start")
        self.kwargs["paper_start"] = kwargs
        if isinstance(self._start, Exception):
            raise self._start
        return self._start


def test_incubation_fails_closed_when_bitpro_raises() -> None:
    client = _RecordingClient(create=RuntimeError("bitpro down"))
    resolver = ARCPaperIncubationResolver(client)
    ok, paper_id, name, msg = resolver.resolve_and_provision_paper_trading(
        _validated(family="atr_breakout", direction="long_only", timeframe="1H"),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg is not None and msg.startswith("bitpro_strategy_create_failed:")
    assert name is not None and "atr_breakout" in name
    assert client.calls == ["strategy_create"]


def test_incubation_fails_closed_when_bitpro_returns_an_error() -> None:
    ok, paper_id, _, msg = ARCPaperIncubationResolver(
        _RecordingClient(create={"status": "error", "message": "denied"})
    ).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg == "bitpro_strategy_create_rejected"


def test_incubation_fails_closed_when_strategy_id_is_missing() -> None:
    ok, paper_id, _, msg = ARCPaperIncubationResolver(
        _RecordingClient(create={"status": "ok", "strategy": {}})
    ).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg == "bitpro_strategy_create_rejected"


def test_incubation_fails_closed_when_configure_fails() -> None:
    client = _RecordingClient(configure=RuntimeError("timeout"))
    ok, paper_id, _, msg = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg is not None and msg.startswith("bitpro_paper_configure_failed:")
    assert client.calls == ["strategy_create", "strategy_get", "paper_configure"]


def test_incubation_fails_closed_when_start_fails() -> None:
    client = _RecordingClient(start={"status": "error"})
    ok, paper_id, _, msg = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg == "bitpro_paper_start_rejected:instance_id=paper_9"
    assert client.calls == ["strategy_create", "strategy_get", "paper_configure", "paper_start"]
    assert client.kwargs["paper_start"]["strategy_id"] == 42


def test_incubation_reuses_self_test_strategy_id() -> None:
    client = _RecordingClient()
    attempt = _validated(family="atr_breakout", timeframe="1m")
    attempt.bitpro_strategy_id = "42"
    ok, paper_id, _, _msg = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        attempt,
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is True
    assert paper_id == "paper_9"
    assert client.calls == ["strategy_get", "paper_configure", "paper_start"]
    assert client.kwargs["paper_configure"]["strategy_id"] == 42


def test_incubation_starts_paper_and_names_from_family() -> None:
    client = _RecordingClient()
    resolver = ARCPaperIncubationResolver(client)
    ok, paper_id, name, _msg = resolver.resolve_and_provision_paper_trading(
        _validated(family="mean_reversion_zscore", direction="short_only", timeframe="4H"),
        PaperPreauthorizationV1(symbols=["ETH-USDT-SWAP"]),
    )
    assert ok is True
    assert paper_id == "paper_9"
    assert client.calls == ["strategy_create", "strategy_get", "paper_configure", "paper_start"]
    assert client.kwargs["paper_configure"]["strategy_id"] == 42
    assert client.kwargs["paper_start"]["strategy_id"] == 42
    assert name == format_bitpro_strategy_name(
        "ETH-USDT-SWAP",
        timeframe="4H",
        logic_summary="mean_reversion_zscore short only",
        capital_u=10000,
    )
    assert "20周期突破" not in (name or "")


def test_incubation_fails_closed_when_configure_omits_instance_id() -> None:
    client = _RecordingClient(configure={"status": "ok", "paper": {}})
    ok, paper_id, _, msg = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg == "bitpro_paper_configure_missing_instance:strategy_id=42"
    assert client.calls == ["strategy_create", "strategy_get", "paper_configure"]


def test_real_session_id_is_not_used_as_start_strategy_id():
    client = _RecordingClient(
        configure={
            "status": "ok",
            "paper": {"configured": True, "strategy_id": 42, "instance_id": "paper_real_session"},
        },
        start={
            "status": "ok",
            "paper": {"started": True, "strategy_id": 42, "instance_id": "paper_real_session"},
        },
    )
    ok, instance, _, _ = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(), PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    )
    assert ok and instance == "paper_real_session"
    assert client.kwargs["paper_start"]["strategy_id"] == 42


def test_changed_remote_code_never_configures_or_starts_paper():
    class Changed(_RecordingClient):
        def strategy_get(self, *, strategy_id):
            self.calls.append("strategy_get")
            return {"status": "ok", "strategy": {"id": strategy_id, "script_content": "changed"}}

    client = Changed()
    attempt = _validated()
    attempt.bitpro_strategy_id = "88"
    ok, instance, _, reason = ARCPaperIncubationResolver(
        client
    ).resolve_and_provision_paper_trading(
        attempt, PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    )
    assert not ok and instance is None and "code" in reason
    assert client.calls == ["strategy_get"]


@pytest.mark.parametrize(
    "reply",
    [
        {"configured": False, "strategy_id": 42, "instance_id": "paper_9"},
        {"configured": True, "strategy_id": 99, "instance_id": "paper_9"},
        {"configured": True, "strategy_id": 42, "operation_id": "operation-not-session"},
        {
            "configured": True,
            "strategy_id": 42,
            "instance_id": "paper_9",
            "strategy_version": "changed",
        },
    ],
)
def test_unbound_configuration_never_starts(reply):
    client = _RecordingClient(configure={"status": "ok", "paper": reply})
    ok, instance, _, _ = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(), PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    )
    assert not ok and instance is None
    assert "paper_start" not in client.calls


@pytest.mark.parametrize(
    "reply",
    [
        {"started": False, "strategy_id": 42, "instance_id": "paper_9"},
        {"started": True, "strategy_id": 99, "instance_id": "paper_9"},
        {"started": True, "strategy_id": 42, "instance_id": "paper_wrong"},
    ],
)
def test_unconfirmed_start_never_reports_paper_running(reply):
    client = _RecordingClient(start={"status": "ok", "paper": reply})
    ok, instance, _, reason = ARCPaperIncubationResolver(
        client
    ).resolve_and_provision_paper_trading(
        _validated(), PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    )
    assert not ok and instance is None and reason == "bitpro_paper_start_identity_unconfirmed"


def test_existing_paper_history_is_never_reconfigured():
    class Existing(_RecordingClient):
        def strategy_get(self, *, strategy_id):
            result = super().strategy_get(strategy_id=strategy_id)
            result["strategy"]["config"]["paper_instance_id"] = "paper_original"
            return result

    client = Existing()
    attempt = _validated()
    attempt.bitpro_strategy_id = "42"
    ok, _, _, reason = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        attempt, PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    )
    assert not ok and reason == "paper_source_already_has_runtime_history"
    assert client.calls == ["strategy_get"]
