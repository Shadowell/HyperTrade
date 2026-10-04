"""Unit and integration tests for Co-STEER strategy domain scaffolding and AST Gatekeeper."""

import builtins
from decimal import Decimal

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
from hypertrade.research.co_steer import (
    ASTGatekeeper,
    BaseEvolutionStrategy,
    LocalSelfHealController,
)


class RecordingIsolatedSandbox:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.sources: list[str] = []

    def smoke_strategy(self, source_code: str) -> str | None:
        self.sources.append(source_code)
        return self.error


class UnavailableIsolatedSandbox:
    def smoke_strategy(self, source_code: str) -> str | None:
        del source_code
        raise RuntimeError("isolated sandbox service is unavailable")


class MockCompliantStrategy(BaseEvolutionStrategy):
    """Compliant test strategy inheriting from BaseEvolutionStrategy."""

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features["ema_fast"] = df["close"].ewm(span=10).mean()
        features["ema_slow"] = df["close"].ewm(span=30).mean()
        features["prev_close"] = df["close"].shift(1)  # Valid backward shift
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index, dtype=int)
        condition_long = features["ema_fast"] > features["ema_slow"]
        signals[condition_long] = 1
        signals[~condition_long] = -1
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        if signal == 0:
            return Decimal("0.0")
        return Decimal("0.50")


def test_base_evolution_strategy_execution() -> None:
    dates = pd.date_range("2026-01-01", periods=10, freq="1h")
    df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, 10),
            "high": np.linspace(101, 112, 10),
            "low": np.linspace(99, 109, 10),
            "close": np.linspace(100, 111, 10),
            "volume": np.ones(10) * 1000,
        },
        index=dates,
    )

    strategy = MockCompliantStrategy(name="TestEMA")
    result = strategy.evaluate_signals(df)

    assert "signal" in result.columns
    assert "position" in result.columns
    assert len(result) == 10
    assert (result["position"].abs() <= 1.0).all()


def test_ast_gatekeeper_compliant_code() -> None:
    compliant_code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class CompliantStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features['lag_close'] = df['close'].shift(1)
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.25")
"""
    val = ASTGatekeeper.validate(compliant_code)
    assert val.valid is True
    assert len(val.errors) == 0


def test_ast_gatekeeper_security_banned_imports() -> None:
    banned_code = """
import os
import subprocess
from socket import socket
from hypertrade.research.co_steer import BaseEvolutionStrategy

class MaliciousStrategy(BaseEvolutionStrategy):
    def compute_features(self, df): return df
    def generate_signals(self, features): return None
    def position_sizing(self, s, f): return 0
"""
    val = ASTGatekeeper.validate(banned_code)
    assert val.valid is False
    assert any("os" in err for err in val.errors)
    assert any("subprocess" in err for err in val.errors)
    assert any("socket" in err for err in val.errors)


def test_ast_gatekeeper_security_dangerous_calls() -> None:
    eval_code = """
from hypertrade.research.co_steer import BaseEvolutionStrategy

class HackStrategy(BaseEvolutionStrategy):
    def compute_features(self, df):
        eval("1+1")
        return df
    def generate_signals(self, f): return None
    def position_sizing(self, s, f): return 0
"""
    val = ASTGatekeeper.validate(eval_code)
    assert val.valid is False
    assert any("eval" in err for err in val.errors)


def test_ast_gatekeeper_rejects_builtins_subscript_escape_and_unbounded_loop() -> None:
    source = """
from hypertrade.research.co_steer import BaseEvolutionStrategy

class EscapeStrategy(BaseEvolutionStrategy):
    def compute_features(self, df):
        __builtins__['open']('/tmp/escaped', 'w')
        while True:
            pass
        return df
    def generate_signals(self, features): return None
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("dunder" in error for error in result.errors)
    assert any("unbounded while" in error for error in result.errors)


def test_ast_gatekeeper_lookahead_forward_shift() -> None:
    lookahead_code = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        # Leaking future price by shifting backwards in time (-1)
        features['future_close'] = df['close'].shift(-1)
        return features

    def generate_signals(self, features): return None
    def position_sizing(self, s, f): return 0
"""
    val = ASTGatekeeper.validate(lookahead_code)
    assert val.valid is False
    assert any("Lookahead bias" in err for err in val.errors)
    assert any("shift with negative offset" in err for err in val.errors)


def test_ast_gatekeeper_lookahead_negative_rolling_and_pct_change() -> None:
    lookahead_code = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features['bad_roll'] = df['close'].rolling(-3).mean()
        features['bad_pct'] = df['close'].pct_change(-1)
        return features

    def generate_signals(self, features): return None
    def position_sizing(self, s, f): return 0
"""
    val = ASTGatekeeper.validate(lookahead_code)
    assert val.valid is False
    assert any("rolling with negative window" in err for err in val.errors)
    assert any("pct_change with negative period" in err for err in val.errors)


def test_ast_gatekeeper_rejects_keyword_and_variable_future_shift() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        k = -1
        features = df.copy()
        features['keyword'] = df['close'].shift(periods=-1)
        features['variable'] = df['close'].shift(k)
        return features
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert sum("shift" in error for error in result.errors) >= 2


def test_ast_gatekeeper_rejects_expanded_kwargs_and_mutated_shift_period() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        k = 1
        k -= 2
        options = {'periods': -1}
        features = df.copy()
        features['expanded'] = df['close'].shift(**options)
        features['mutated'] = df['close'].shift(k)
        return features
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("expanded keyword" in error for error in result.errors)
    assert any("statically non-negative" in error for error in result.errors)


def test_ast_gatekeeper_rejects_uncertain_shift_period() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class UncertainStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(lag=df['close'].shift(self.params['periods']))
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("statically non-negative" in error for error in result.errors)


def test_ast_gatekeeper_rejects_full_sample_statistics_and_reverse_iloc() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class GlobalStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features['normalized'] = df['close'] / df['close'].mean()
        return features.iloc[::-1]
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("full-sample statistic" in error for error in result.errors)
    assert any("reverse iloc" in error for error in result.errors)


def test_ast_gatekeeper_rejects_signal_global_statistic_and_centered_rolling() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class SignalLeakStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(centered=df['close'].rolling(5, center=True).mean())
    def generate_signals(self, features):
        return (features['close'] > features['close'].mean()).astype(int)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("centered rolling" in error for error in result.errors)
    assert any("full-sample statistic" in error for error in result.errors)


def test_ast_gatekeeper_rejects_allowlisted_but_uninstalled_dependencies() -> None:
    source = """
import scipy
import talib
from hypertrade.research.co_steer import BaseEvolutionStrategy

class DependencyProbe(BaseEvolutionStrategy):
    def compute_features(self, df): return df
    def generate_signals(self, features): return None
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is False
    assert any("scipy" in error for error in result.errors)
    assert any("talib" in error for error in result.errors)


def test_ast_gatekeeper_allows_windowed_mean() -> None:
    source = """
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class RollingStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(average=df['close'].rolling(3).mean())
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return 0
"""

    result = ASTGatekeeper.validate(source)

    assert result.valid is True, result.errors


def test_ast_gatekeeper_missing_required_methods() -> None:
    incomplete_code = """
from hypertrade.research.co_steer import BaseEvolutionStrategy

class IncompleteStrategy(BaseEvolutionStrategy):
    def compute_features(self, df): return df
    # Missing generate_signals and position_sizing
"""
    val = ASTGatekeeper.validate(incomplete_code)
    assert val.valid is False
    assert any("missing methods" in err for err in val.errors)


def test_local_self_heal_success_first_attempt() -> None:
    valid_code = """
from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class SimpleGoodStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df
    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(0, index=features.index)
    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.0")
"""
    sandbox = RecordingIsolatedSandbox()
    res = LocalSelfHealController.attempt_compile_and_heal(valid_code, sandbox=sandbox)
    assert res.success is True
    assert res.attempts == 1
    assert res.strategy_digest.startswith("sha256:")
    assert len(res.errors) == 0
    assert sandbox.sources == [valid_code]


def test_local_self_heal_never_executes_generated_code_in_host(monkeypatch) -> None:
    valid_code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class HostEscapeProbe(BaseEvolutionStrategy):
    def compute_features(self, df): return df
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return Decimal('0')
"""
    sandbox = RecordingIsolatedSandbox()

    def deny_host_exec(*args, **kwargs):
        raise AssertionError("generated code reached host exec")

    monkeypatch.setattr(builtins, "exec", deny_host_exec)

    result = LocalSelfHealController.attempt_compile_and_heal(valid_code, sandbox=sandbox)

    assert result.success is True
    assert sandbox.sources == [valid_code]


def test_local_self_heal_fails_closed_when_isolated_sandbox_is_unavailable() -> None:
    valid_code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class UnavailableProbe(BaseEvolutionStrategy):
    def compute_features(self, df): return df
    def generate_signals(self, features): return pd.Series(0, index=features.index)
    def position_sizing(self, signal, features): return Decimal('0')
"""

    result = LocalSelfHealController.attempt_compile_and_heal(
        valid_code,
        sandbox=UnavailableIsolatedSandbox(),
        max_retries=0,
    )

    assert result.success is False
    assert result.errors == [
        "Isolated sandbox unavailable: isolated sandbox service is unavailable"
    ]


def test_local_self_heal_repaired_successfully() -> None:
    buggy_code = """
from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class LeakyThenHealedStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features['future'] = df['close'].shift(-1)
        return features
    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)
    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.1")
"""

    def mock_repair_callback(broken_code: str, errors: list[str]) -> str:
        # Simulate local LLM repair: replace lookahead shift(-1) with lag shift(1)
        return broken_code.replace("shift(-1)", "shift(1)")

    res = LocalSelfHealController.attempt_compile_and_heal(
        buggy_code,
        sandbox=RecordingIsolatedSandbox(),
        repair_callback=mock_repair_callback,
        max_retries=2,
    )

    assert res.success is True
    assert res.attempts == 2
    assert "shift(1)" in res.final_code
    assert res.strategy_digest.startswith("sha256:")
    assert len(res.repair_logs) == 1
    assert "Attempt 1 failed" in res.repair_logs[0]


def test_local_self_heal_max_retries_exceeded() -> None:
    hopeless_code = """
import os
import subprocess
"""
    # Callback fails to fix the issue
    def mock_useless_callback(code: str, errors: list[str]) -> str:
        return code + "\n# Still broken"

    res = LocalSelfHealController.attempt_compile_and_heal(
        hopeless_code,
        sandbox=RecordingIsolatedSandbox(),
        repair_callback=mock_useless_callback,
        max_retries=2,
    )

    assert res.success is False
    assert res.attempts == 3
    assert len(res.repair_logs) == 3
    assert len(res.errors) > 0
