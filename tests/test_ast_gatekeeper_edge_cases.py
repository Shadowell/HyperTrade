"""Parametric corner-case and edge-case unit tests for ASTGatekeeper.

Validates that complex Python AST expressions (walrus operator, multi-assignment,
type annotations, pattern matching, obscured reflection, and dunder access)
are strictly parsed and enforced according to security & anti-lookahead rules.
"""

from __future__ import annotations

import pytest
from hypertrade.research.co_steer import ASTGatekeeper


def test_ast_gatekeeper_allows_walrus_in_comprehensions() -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class WalrusStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features['derived'] = [v for x in df['close'] if (v := float(x)) > 0]
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""
    val = ASTGatekeeper.validate(code, market="global")
    assert val.valid is True
    assert len(val.errors) == 0


def test_ast_gatekeeper_allows_annotated_and_multi_assignments() -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class AnnotatedStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        step: int = 1
        a = b = Decimal("0.25")
        features['momentum'] = df['close'].diff(step)
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""
    val = ASTGatekeeper.validate(code, market="global")
    assert val.valid is True
    assert len(val.errors) == 0


def test_ast_gatekeeper_allows_python_match_case() -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class PatternMatchingStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        match signal:
            case 1:
                return Decimal("0.5")
            case 0:
                return Decimal("0.0")
            case _:
                return Decimal("0.0")
"""
    val = ASTGatekeeper.validate(code, market="global")
    assert val.valid is True
    assert len(val.errors) == 0


def test_ast_gatekeeper_blocks_obscured_dunder_reflection() -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class MaliciousDunderStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        subclasses = df.__class__.__bases__[0].__subclasses__()
        return df

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""
    val = ASTGatekeeper.validate(code, market="global")
    assert val.valid is False
    assert any(
        "__subclasses__" in err or "__bases__" in err or "banned" in err.lower()
        for err in val.errors
    )


def test_ast_gatekeeper_blocks_builtin_getattr_injection() -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class ReflectiveStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        ev = getattr(__builtins__, 'ev' + 'al')
        ev('print("escaped")')
        return df

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=features.index)

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""
    val = ASTGatekeeper.validate(code, market="global")
    assert val.valid is False
    assert any("getattr" in err or "eval" in err or "__builtins__" in err for err in val.errors)


@pytest.mark.parametrize("market,expected_valid", [
    ("global", True),
    ("cn", False),
])
def test_ast_gatekeeper_market_aware_short_signal_distinction(
    market: str, expected_valid: bool
) -> None:
    code = """
import pandas as pd
from decimal import Decimal
from hypertrade.research.co_steer import BaseEvolutionStrategy

class ShortingStrategy(BaseEvolutionStrategy):
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index)
        signals[features['close'] <= 100] = -1
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        return Decimal("0.5")
"""
    val = ASTGatekeeper.validate(code, market=market)
    assert val.valid is expected_valid
    if not expected_valid:
        assert any("A-Share" in err or "-1" in err or "short" in err.lower() for err in val.errors)
