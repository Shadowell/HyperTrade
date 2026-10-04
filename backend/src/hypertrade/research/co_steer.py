"""Co-STEER: Code-generation with Structural Constraints, AST Gatekeeper and Self-Healing.

Implements:
1. BaseEvolutionStrategy: unified three-stage strategy domain scaffolding.
2. ASTGatekeeper: security filtering, lookahead bias (future leakage) detection,
   and structural interface enforcement.
3. LocalSelfHealController: localized error capture and bounded repair loop
   without polluting global mission context.
"""

from __future__ import annotations

import ast
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


class BaseEvolutionStrategy(ABC):
    """Unified strategy domain scaffolding for Co-STEER strategy synthesis."""

    def __init__(self, name: str = "CoSteerStrategy", params: dict[str, Any] | None = None) -> None:
        self.name = name
        self.params = params or {}

    @abstractmethod
    def compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute pure-function features and indicators on historical OHLCV data."""
        pass

    @abstractmethod
    def generate_signals(self, features: pd.DataFrame) -> pd.Series:
        """Generate trade signals: 1 (long), -1 (short), 0 (flat/hold)."""
        pass

    @abstractmethod
    def position_sizing(self, signal: int, features: pd.DataFrame) -> Decimal:
        """Determine position fraction (0.0 to 1.0) based on signal and volatility."""
        pass

    def evaluate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Run the full pipeline and return signals & positions aligned with df index."""
        features = self.compute_features(df)
        signals = self.generate_signals(features)
        positions = pd.Series(0.0, index=df.index, dtype=float)

        for idx in df.index:
            sig = int(signals.loc[idx])
            size = float(self.position_sizing(sig, features.loc[[idx]]))
            positions.loc[idx] = sig * size

        return pd.DataFrame({"signal": signals, "position": positions}, index=df.index)


@dataclass
class ASTValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ASTGatekeeper:
    """Static AST parser enforcing security, no-lookahead, and structural compliance."""

    BANNED_MODULES: frozenset[str] = frozenset(
        {
            "os",
            "sys",
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "httpx",
            "aiohttp",
            "shutil",
            "pathlib",
            "posix",
            "pty",
            "builtins",
            "importlib",
        }
    )

    ALLOWED_MODULES: frozenset[str] = frozenset(
        {
            "numpy",
            "np",
            "pandas",
            "pd",
            "scipy",
            "talib",
            "math",
            "decimal",
            "datetime",
            "collections",
            "typing",
            "dataclasses",
            "abc",
            "hypertrade",
        }
    )

    BANNED_CALLS: frozenset[str] = frozenset(
        {
            "eval",
            "exec",
            "open",
            "__import__",
            "compile",
            "globals",
            "locals",
            "vars",
            "breakpoint",
        }
    )

    REQUIRED_METHODS: frozenset[str] = frozenset(
        {
            "compute_features",
            "generate_signals",
            "position_sizing",
        }
    )

    @classmethod
    def validate(cls, source_code: str) -> ASTValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return ASTValidationResult(
                valid=False,
                errors=[f"SyntaxError on line {e.lineno}: {e.msg}"],
            )

        found_strategy_class = False
        implemented_methods: set[str] = set()

        for node in ast.walk(tree):
            # 1. Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    if root_pkg in cls.BANNED_MODULES:
                        errors.append(f"Security violation: banned module imported: {alias.name}")
                    elif root_pkg not in cls.ALLOWED_MODULES:
                        errors.append(f"Disallowed module import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    if root_pkg in cls.BANNED_MODULES:
                        errors.append(f"Security violation: banned import: {node.module}")
                    elif root_pkg not in cls.ALLOWED_MODULES:
                        errors.append(f"Disallowed module import: {node.module}")

            # 2. Check dangerous calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in cls.BANNED_CALLS:
                        errors.append(f"Security violation: banned function call: {node.func.id}()")
                elif isinstance(node.func, ast.Attribute):
                    if node.func.attr in cls.BANNED_CALLS:
                        errors.append(f"Security violation: banned method call: {node.func.attr}()")
                    if node.func.attr in {"__subclasses__", "__bases__", "__class__"}:
                        errors.append(f"Security violation: reflection escape: {node.func.attr}")

                # 3. Lookahead bias detection (Future leakage)
                if isinstance(node.func, ast.Attribute):
                    if node.func.attr == "shift":
                        if node.args and cls._is_negative_literal(node.args[0]):
                            errors.append(
                                "Lookahead bias violation: forward shift with negative offset "
                                "leaks future data"
                            )
                    elif node.func.attr == "rolling":
                        if node.args and cls._is_negative_literal(node.args[0]):
                            errors.append(
                                "Lookahead bias violation: rolling with negative window "
                                "is forbidden"
                            )
                    elif (
                        node.func.attr in {"lead", "pct_change"}
                        and node.args
                        and cls._is_negative_literal(node.args[0])
                    ):
                        errors.append(
                            f"Lookahead bias violation: {node.func.attr} with negative period "
                            "leaks future data"
                        )

            # 4. Check class definition & required methods
            elif isinstance(node, ast.ClassDef):
                found_strategy_class = True
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        implemented_methods.add(item.name)

        if not found_strategy_class:
            errors.append("Structure violation: no strategy class definition found")
        else:
            missing = cls.REQUIRED_METHODS - implemented_methods
            if missing:
                errors.append(f"Structure violation: missing methods: {sorted(missing)}")

        return ASTValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _is_negative_literal(node: ast.expr) -> bool:
        """Check if an AST expression represents a negative literal number."""
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
        ):
            return node.operand.value > 0
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value < 0
        return False


@dataclass
class SelfHealResult:
    success: bool
    final_code: str
    attempts: int
    repair_logs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strategy_digest: str = ""


class LocalSelfHealController:
    """Executes local self-healing for generated strategy code."""

    @classmethod
    def attempt_compile_and_heal(
        cls,
        initial_code: str,
        *,
        repair_callback: Callable[[str, list[str]], str] | None = None,
        max_retries: int = 2,
    ) -> SelfHealResult:
        current_code = initial_code
        repair_logs: list[str] = []
        last_errors: list[str] = []

        for attempt in range(max_retries + 1):
            validation = ASTGatekeeper.validate(current_code)
            if validation.valid:
                # Test dry execution inside an isolated safe namespace
                exec_error = cls._dry_run_instantiate(current_code)
                if exec_error is None:
                    raw_hash = hashlib.sha256(current_code.encode("utf-8")).hexdigest()[:20]
                    return SelfHealResult(
                        success=True,
                        final_code=current_code,
                        attempts=attempt + 1,
                        repair_logs=repair_logs,
                        strategy_digest=f"sha256:{raw_hash}",
                    )
                validation.errors.append(exec_error)

            last_errors = validation.errors
            repair_logs.append(f"Attempt {attempt + 1} failed: {'; '.join(validation.errors)}")

            if attempt < max_retries and repair_callback is not None:
                current_code = repair_callback(current_code, validation.errors)
            else:
                break

        return SelfHealResult(
            success=False,
            final_code=current_code,
            attempts=max_retries + 1,
            repair_logs=repair_logs,
            errors=last_errors,
        )

    @staticmethod
    def _dry_run_instantiate(source_code: str) -> str | None:
        """Instantiate strategy class inside an isolated mock namespace."""
        safe_globals: dict[str, Any] = {
            "BaseEvolutionStrategy": BaseEvolutionStrategy,
            "pd": pd,
            "np": np,
            "Decimal": Decimal,
            "ABC": ABC,
            "abstractmethod": abstractmethod,
            "Any": Any,
        }
        try:
            compiled = compile(source_code, "<co_steer_sandbox>", "exec")
            exec(compiled, safe_globals)
        except Exception as e:
            return f"Runtime error during execution: {type(e).__name__}: {e}"

        # Find instantiated strategy class
        strategy_class = None
        for obj in safe_globals.values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseEvolutionStrategy)
                and obj is not BaseEvolutionStrategy
            ):
                strategy_class = obj
                break

        if strategy_class is None:
            return "No subclass of BaseEvolutionStrategy was defined in the source"

        try:
            strategy_class()
        except Exception as e:
            return f"Failed to instantiate strategy constructor: {type(e).__name__}: {e}"

        return None
