"""QuantLab Strategy Transpiler & Matrix Scaffold.

Transpiles HyperTrade Co-STEER synthesized strategies (subclassing
``BaseEvolutionStrategy``) into standalone, validated QuantLab Python
modules adhering to the ``market-evolution.v1`` and ``MatrixStrategy`` contract.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from hypertrade.research.co_steer import ASTGatekeeper, BaseEvolutionStrategy


@dataclass(frozen=True)
class TranspiledQuantLabStrategy:
    """Artifact of transpiling a strategy for the QuantLab engine."""

    strategy_id: str
    name: str
    code: str
    code_sha256: str
    meta: dict[str, Any]
    parameters: dict[str, Any]
    market: str = "cn"
    timeframe: str = "1D"
    symbols: tuple[str, ...] = ("000001.SZ",)


_BASE_EVO_SCAFFOLD = """
from abc import ABC, abstractmethod

class BaseEvolutionStrategy(ABC):
    \"\"\"Scaffold base strategy for Co-STEER strategy synthesis.\"\"\"
    def __init__(self, name: str = "CoSteerStrategy", params: dict | None = None) -> None:
        self.name = name
        self.params = params or {}

    @abstractmethod
    def compute_features(self, df: Any) -> Any:
        pass

    @abstractmethod
    def generate_signals(self, features: Any) -> Any:
        pass

    @abstractmethod
    def position_sizing(self, signal: int, features: Any) -> Any:
        pass
"""


class QuantLabStrategyTranspiler:
    """Translates Co-STEER strategies to QuantLab native MatrixStrategy format."""

    @classmethod
    def transpile_code(
        cls,
        code: str,
        *,
        strategy_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        market: str = "cn",
        timeframe: str = "1D",
        symbols: Sequence[str] | None = None,
        parameters: dict[str, Any] | None = None,
        stop_loss: float = -0.08,
        max_hold_days: int = 20,
    ) -> TranspiledQuantLabStrategy:
        """Transpile strategy source code into a QuantLab module.

        Validates AST safety and temporal causality (no lookahead bias).
        """
        raw_code = code.strip()
        if not raw_code:
            raise ValueError("strategy_code_empty")

        # 1. Check if the code is already a native QuantLab strategy module
        if "MATRIX_STRATEGY" in raw_code and "META" in raw_code:
            cls._validate_ast_safety(raw_code, is_native_matrix=True, market=market)
            return cls._wrap_native_quantlab_strategy(
                raw_code,
                strategy_id=strategy_id,
                name=name,
                market=market,
                timeframe=timeframe,
                symbols=symbols,
                parameters=parameters,
            )

        # 2. First-pass AST validation on BaseEvolutionStrategy input code
        cls._validate_ast_safety(raw_code, is_native_matrix=False, market=market)

        # 3. Detect strategy class name
        tree = ast.parse(raw_code)
        strategy_class_name = cls._find_strategy_class_name(tree)

        # 4. Construct strategy identity
        sid = str(strategy_id or "").strip()
        if not sid:
            # Derive strategy_id from class name
            clean_name = re.sub(r"(?<!^)(?=[A-Z])", "_", strategy_class_name).lower()
            sid = f"ai_{clean_name}" if not clean_name.startswith("ai_") else clean_name
        sname = str(name or strategy_class_name).strip()
        sdesc = str(description or f"Co-STEER generated strategy {sname}").strip()
        syms = tuple(symbols or (["000001.SZ"] if market == "cn" else ["SPY.US"]))
        params = dict(parameters or {})

        # Convert params to QuantLab META param list
        params_meta = [
            {
                "id": k,
                "label": k,
                "type": "float" if isinstance(v, (int, float)) else "str",
                "default": v,
            }
            for k, v in params.items()
        ]

        # 5. Build self-contained module code
        clean_code = raw_code
        # If BaseEvolutionStrategy is imported from hypertrade, replace or strip the import
        clean_code = re.sub(
            r"from\s+hypertrade\.research\.co_steer\s+import\s+BaseEvolutionStrategy",
            "",
            clean_code,
        ).strip()

        wrapper_name = f"{strategy_class_name}MatrixAdapter"
        meta_dict = {
            "id": sid,
            "name": sname,
            "description": sdesc,
            "strategy_type": "趋势",
            "asset_types": ["stock"],
            "timeframes": [timeframe.lower()],
            "params": params_meta,
            "scoring": {},
            "order_by": "score",
            "descending": True,
            "limit": 100,
            "execution_backend": "matrix_native",
        }

        meta_json = json.dumps(meta_dict, ensure_ascii=False, indent=4)

        scaffold_header = f'''"""QuantLab Matrix Strategy generated by HyperTrade.

Strategy ID: {sid}
Target Market: {market}
Timeframe: {timeframe}
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd
from app.backtest.matrix import MatrixStrategy, make_signal_matrix, MarketDataMatrix, SignalMatrix

META = {meta_json}

ENTRY_SIGNALS = ["signal_long_entry"]
EXIT_SIGNALS = ["signal_long_exit"]
STOP_LOSS = {stop_loss}
MAX_HOLD_DAYS = {max_hold_days}
EXECUTION_BACKEND = "matrix_native"

{_BASE_EVO_SCAFFOLD}

# -----------------------------------------------------------------------------
# Core Synthesized Strategy Logic
# -----------------------------------------------------------------------------
{clean_code}

# -----------------------------------------------------------------------------
# QuantLab Vectorized Matrix Wrapper
# -----------------------------------------------------------------------------
class {wrapper_name}(MatrixStrategy):
    def __init__(self, evo_strat: Any = None) -> None:
        self._evo = evo_strat or {strategy_class_name}()

    def required_fields(self) -> frozenset[str]:
        return frozenset({{"open", "high", "low", "close", "volume"}})

    def required_warmup_bars(self, params: dict[str, Any]) -> int:
        del params
        return 30

    def compute_signals(
        self,
        market: MarketDataMatrix,
        params: dict[str, Any],
    ) -> SignalMatrix:
        num_bars, num_assets = market.shape
        entry_matrix = np.zeros(market.shape, dtype=np.uint8)
        exit_matrix = np.zeros(market.shape, dtype=np.uint8)

        for j in range(num_assets):
            df = pd.DataFrame({{
                "open": market.open[:, j],
                "high": market.high[:, j],
                "low": market.low[:, j],
                "close": market.close[:, j],
                "volume": market.volume[:, j],
            }})
            try:
                features = self._evo.compute_features(df)
                signals = self._evo.generate_signals(features)
                sig_arr = np.asarray(signals)
                entry_matrix[:, j] = np.where(sig_arr == 1, 1, 0).astype(np.uint8)
                exit_matrix[:, j] = np.where(sig_arr <= 0, 1, 0).astype(np.uint8)
            except Exception:
                pass

        return make_signal_matrix(
            market.shape,
            entry=entry_matrix,
            exit=exit_matrix,
            entry_signal_code=np.where(entry_matrix > 0, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_matrix > 0, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_long_entry",),
            exit_signal_ids=("signal_long_exit",),
        )


MATRIX_STRATEGY = {wrapper_name}()
'''

        # 6. Safety validation on the fully generated code
        cls._validate_ast_safety(scaffold_header, is_native_matrix=True, market=market)

        code_hash = hashlib.sha256(scaffold_header.encode("utf-8")).hexdigest()

        return TranspiledQuantLabStrategy(
            strategy_id=sid,
            name=sname,
            code=scaffold_header,
            code_sha256=code_hash,
            meta=meta_dict,
            parameters=params,
            market=market,
            timeframe=timeframe,
            symbols=syms,
        )

    @classmethod
    def generate_default_evolution_code(
        cls,
        class_name: str = "MovingAverageCrossStrategy",
        fast_window: int = 5,
        slow_window: int = 20,
        market: str = "cn",
    ) -> str:
        """Generate a compliant BaseEvolutionStrategy code snippet."""
        clean_cls = re.sub(r"[^a-zA-Z0-9_]", "", class_name)
        if not clean_cls or clean_cls[0].isdigit():
            clean_cls = f"Strategy{clean_cls}"

        short_sig = "0" if market.lower() in ("cn", "a_share", "ashare") else "-1"

        return f'''from decimal import Decimal
import pandas as pd
from hypertrade.research.co_steer import BaseEvolutionStrategy

class {clean_cls}(BaseEvolutionStrategy):
    """Moving Average Crossover Evolution Strategy synthesized by HyperTrade."""

    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = df.copy()
        features["fast_ma"] = features["close"].rolling({int(fast_window)}).mean()
        features["slow_ma"] = features["close"].rolling({int(slow_window)}).mean()
        return features

    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        signals = pd.Series(0, index=features.index)
        long_cond = features["fast_ma"] > features["slow_ma"]
        short_cond = features["fast_ma"] < features["slow_ma"]
        signals[long_cond] = 1
        signals[short_cond] = {short_sig}
        return signals

    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        if signal == 0:
            return Decimal("0.0")
        return Decimal("1.0")
'''

    @classmethod
    def transpile_instance(
        cls,
        strategy_instance: BaseEvolutionStrategy,
        *,
        strategy_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        market: str = "cn",
        timeframe: str = "1D",
        symbols: Sequence[str] | None = None,
    ) -> TranspiledQuantLabStrategy:
        """Transpile a live strategy instance by extracting its source."""
        source_code = inspect.getsource(type(strategy_instance))
        return cls.transpile_code(
            source_code,
            strategy_id=strategy_id,
            name=name or strategy_instance.name,
            description=description,
            market=market,
            timeframe=timeframe,
            symbols=symbols,
            parameters=strategy_instance.params,
        )

    @classmethod
    def _validate_ast_safety(
        cls,
        code: str,
        is_native_matrix: bool = False,
        market: str = "cn",
    ) -> None:
        """Run ASTGatekeeper rules to block unsafe modules or lookahead bias."""
        result = ASTGatekeeper.validate(code, market=market)
        if not result.valid:
            if is_native_matrix:
                critical_errors = [
                    err
                    for err in result.errors
                    if not err.startswith("Structure violation:")
                    and "Disallowed module import: app" not in err
                ]
                if critical_errors:
                    raise ValueError(
                        f"transpiler_ast_validation_failed: {', '.join(critical_errors)}"
                    )
            else:
                raise ValueError(
                    f"transpiler_ast_validation_failed: {', '.join(result.errors)}"
                )

    @classmethod
    def _find_strategy_class_name(cls, tree: ast.Module) -> str:
        """Find the strategy class implementing compute_features."""
        classes: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                # Check base classes or methods
                has_compute_features = any(
                    isinstance(m, ast.FunctionDef) and m.name == "compute_features"
                    for m in node.body
                )
                if has_compute_features:
                    return node.name
                classes.append(node.name)
        if classes:
            return classes[-1]
        raise ValueError("no_strategy_class_found_in_code")

    @classmethod
    def _wrap_native_quantlab_strategy(
        cls,
        code: str,
        *,
        strategy_id: str | None,
        name: str | None,
        market: str,
        timeframe: str,
        symbols: Sequence[str] | None,
        parameters: dict[str, Any] | None,
    ) -> TranspiledQuantLabStrategy:
        """Handle code that is already a valid QuantLab strategy module."""
        sid = strategy_id or "quantlab_native_strat"
        sname = name or sid
        syms = tuple(symbols or (["000001.SZ"] if market == "cn" else ["SPY.US"]))
        params = dict(parameters or {})
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()

        return TranspiledQuantLabStrategy(
            strategy_id=sid,
            name=sname,
            code=code,
            code_sha256=code_hash,
            meta={"id": sid, "name": sname, "execution_backend": "matrix_native"},
            parameters=params,
            market=market,
            timeframe=timeframe,
            symbols=syms,
        )
