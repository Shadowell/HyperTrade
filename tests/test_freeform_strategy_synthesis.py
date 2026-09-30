from __future__ import annotations

from hypertrade.research.synthesis import (
    FreeformStrategySynthesizer,
)


def test_freeform_strategy_synthesis_valid_code() -> None:
    code = (
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "\n"
        "\n"
        "class AdaptiveMultiFactorStrategy(BaseStrategy):\n"
        '    """Autonomous multi-factor breakout strategy."""\n'
        "\n"
        "    async def on_init(self):\n"
        "        self.p_fast_window = 14\n"
        "        self.p_threshold = 0.015\n"
        "\n"
        "    async def on_bar(self, bar: BarData):\n"
        "        if bar.close_price > 60500.0:\n"
        '            await self.open_contract("BTC-USDT-SWAP", "long", 0.01)\n'
        "        return None\n"
    )

    synthesizer = FreeformStrategySynthesizer()
    res = synthesizer.synthesize(custom_code=code)

    assert res.is_freeform is True
    assert res.class_name == "AdaptiveMultiFactorStrategy"
    assert res.validation.is_valid is True
    assert res.validation.rejections == []
    assert "fast_window" in res.tunable_parameters
    assert res.tunable_parameters["fast_window"] == 14
    assert res.smoke_test.passed is True
    assert res.smoke_test.bars_processed == 10
    assert res.smoke_test.orders_simulated > 0


def test_freeform_strategy_synthesis_rejects_malicious_code() -> None:
    malicious_code = (
        "import os\n"
        "from app.core.execution.base_strategy import BaseStrategy\n"
        "\n"
        "\n"
        "class MaliciousStrategy(BaseStrategy):\n"
        "    async def on_bar(self, bar: BarData):\n"
        '        os.system("rm -rf /")\n'
        "        return None\n"
    )

    synthesizer = FreeformStrategySynthesizer()
    res = synthesizer.synthesize(custom_code=malicious_code)

    assert res.validation.is_valid is False
    assert any("process_execution" in r or "os" in r for r in res.validation.rejections)
    assert res.smoke_test.passed is False


def test_freeform_strategy_synthesis_syntax_error() -> None:
    broken_code = (
        "class BrokenStrategy(BaseStrategy:\n"
        "    async def on_bar(self, bar: BarData):\n"
        "        pass\n"
    )

    synthesizer = FreeformStrategySynthesizer()
    res = synthesizer.synthesize(custom_code=broken_code)

    assert res.validation.is_valid is False
    assert any("invalid_python_syntax" in r for r in res.validation.rejections)
    assert res.smoke_test.passed is False


def test_dual_track_spec_compatibility() -> None:
    spec = {
        "schema_version": "research_strategy_spec.v1",
        "mandate_id": "rman_test",
        "strategy_key": "dual_track_probe",
        "title": "Dual track validation probe",
        "hypothesis": "momentum persistence after ema crossover",
        "symbols": ["BTC"],
        "timeframes": ["1H"],
        "strategy_category": "TREND",
        "entry_logic": "fast ema crosses slow ema",
        "exit_logic": "reverse cross",
        "risk_conditions": ["bounded notional"],
        "data_requirements": ["ohlcv"],
        "parameter_bounds": {},
        "invalidation_conditions": ["insufficient data"],
    }

    synthesizer = FreeformStrategySynthesizer()
    res = synthesizer.synthesize(spec=spec)

    assert res.is_freeform is False
    assert res.class_name.startswith("Research")
    assert res.validation.is_valid is True
    assert res.validation.rejections == []
    assert res.smoke_test.passed is True
    assert res.smoke_test.bars_processed == 10
