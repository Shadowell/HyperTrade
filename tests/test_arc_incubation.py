"""Paper provision must fail closed and must call configure + start."""

from typing import Any

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
        self._create = create if create is not None else {
            "status": "ok",
            "strategy": {"id": 42},
        }
        self._configure = configure if configure is not None else {
            "status": "ok",
            "paper": {"instance_id": 9},
        }
        self._start = start if start is not None else {
            "status": "ok",
            "paper": {"instance_id": 9, "status": "running"},
        }

    def strategy_create(self, **kwargs: Any) -> Any:
        self.calls.append("strategy_create")
        self.kwargs["strategy_create"] = kwargs
        if isinstance(self._create, Exception):
            raise self._create
        return self._create

    def paper_configure(self, **kwargs: Any) -> Any:
        self.calls.append("paper_configure")
        self.kwargs["paper_configure"] = kwargs
        if isinstance(self._configure, Exception):
            raise self._configure
        return self._configure

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
    assert client.calls == ["strategy_create", "paper_configure"]


def test_incubation_fails_closed_when_start_fails() -> None:
    client = _RecordingClient(start={"status": "error"})
    ok, paper_id, _, msg = ARCPaperIncubationResolver(client).resolve_and_provision_paper_trading(
        _validated(),
        PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"]),
    )
    assert ok is False
    assert paper_id is None
    assert msg == "bitpro_paper_start_rejected:instance_id=9"
    assert client.calls == ["strategy_create", "paper_configure", "paper_start"]
    assert client.kwargs["paper_start"]["strategy_id"] == 9


def test_incubation_starts_paper_and_names_from_family() -> None:
    client = _RecordingClient()
    resolver = ARCPaperIncubationResolver(client)
    ok, paper_id, name, _msg = resolver.resolve_and_provision_paper_trading(
        _validated(family="mean_reversion_zscore", direction="short_only", timeframe="4H"),
        PaperPreauthorizationV1(symbols=["ETH-USDT-SWAP"]),
    )
    assert ok is True
    assert paper_id == "9"
    assert client.calls == ["strategy_create", "paper_configure", "paper_start"]
    assert client.kwargs["paper_configure"]["strategy_id"] == 42
    assert client.kwargs["paper_start"]["strategy_id"] == 9
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
    assert client.calls == ["strategy_create", "paper_configure"]
