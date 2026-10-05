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
from typing import Any, Protocol

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
            "__future__",
            "numpy",
            "np",
            "pandas",
            "pd",
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
    def validate(cls, source_code: str, *, market: str = "global") -> ASTValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            return ASTValidationResult(
                valid=False,
                errors=[f"SyntaxError on line {e.lineno}: {e.msg}"],
            )

        parents = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        numeric_constants = cls._constant_bindings(tree)
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
                        if cls._has_expanded_keywords(node):
                            errors.append(
                                "Lookahead bias violation: shift expanded keyword arguments "
                                "cannot be statically verified"
                            )
                        else:
                            period = cls._call_argument(node, position=0, keywords={"periods"})
                            period_value = cls._numeric_value(period, numeric_constants)
                            if period is not None and period_value is None:
                                errors.append(
                                    "Lookahead bias violation: shift period must be statically "
                                    "non-negative"
                                )
                            elif period_value is not None and period_value < 0:
                                errors.append(
                                    "Lookahead bias violation: forward shift with negative offset "
                                    "leaks future data"
                                )
                    elif node.func.attr == "rolling":
                        window = cls._call_argument(node, position=0, keywords={"window"})
                        window_value = cls._numeric_value(window, numeric_constants)
                        center = cls._call_argument(node, position=2, keywords={"center"})
                        if cls._has_expanded_keywords(node):
                            errors.append(
                                "Lookahead bias violation: rolling expanded keyword arguments "
                                "cannot be statically verified"
                            )
                        elif window is not None and window_value is None:
                            errors.append(
                                "Lookahead bias violation: rolling window must be "
                                "statically positive"
                            )
                        elif window_value is not None and window_value < 0:
                            errors.append(
                                "Lookahead bias violation: rolling with negative window "
                                "is forbidden"
                            )
                        if not cls._is_literal_false(center):
                            errors.append(
                                "Lookahead bias violation: centered rolling windows may consume "
                                "future rows"
                            )
                    elif node.func.attr in {"lead", "pct_change"}:
                        if cls._has_expanded_keywords(node):
                            errors.append(
                                f"Lookahead bias violation: {node.func.attr} expanded keyword "
                                "arguments cannot be statically verified"
                            )
                        else:
                            period = cls._call_argument(node, position=0, keywords={"periods"})
                            period_value = cls._numeric_value(period, numeric_constants)
                            if period is not None and period_value is None:
                                errors.append(
                                    f"Lookahead bias violation: {node.func.attr} period must be "
                                    "statically non-negative"
                                )
                            elif period_value is not None and period_value < 0:
                                errors.append(
                                    f"Lookahead bias violation: {node.func.attr} with negative "
                                    "period leaks future data"
                                )
                    elif (
                        node.func.attr in {"mean", "median", "std", "var", "quantile"}
                        and cls._enclosing_function(node, parents)
                        in {"compute_features", "generate_signals"}
                        and not cls._uses_bounded_window(node.func.value)
                    ):
                        errors.append(
                            "Lookahead bias violation: full-sample statistic in strategy pipeline "
                            "must use a bounded rolling or expanding window"
                        )

            elif isinstance(node, ast.Name) and node.id.startswith("__"):
                errors.append(f"Security violation: dunder name access is forbidden: {node.id}")

            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                errors.append(
                    f"Security violation: dunder attribute access is forbidden: {node.attr}"
                )

            elif isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and bool(
                node.test.value
            ):
                errors.append("Security violation: unbounded while loop is forbidden")

            elif isinstance(node, ast.Subscript) and cls._is_reverse_iloc(node):
                errors.append("Lookahead bias violation: reverse iloc traversal is forbidden")

            # 4. Check class definition & required methods
            elif isinstance(node, ast.ClassDef):
                found_strategy_class = True
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        implemented_methods.add(item.name)

            # 5. Check China A-Share spot long-only constraint (no shorting)
            if market.lower() in ("cn", "a_share", "ashare"):
                enclosing = cls._enclosing_function(node, parents)
                if enclosing == "generate_signals":
                    if isinstance(node, ast.Assign):
                        for tgt in node.targets:
                            is_sig = (
                                (isinstance(tgt, ast.Name) and "signal" in tgt.id.lower())
                                or (
                                    isinstance(tgt, ast.Subscript)
                                    and isinstance(tgt.value, ast.Name)
                                    and "signal" in tgt.value.id.lower()
                                )
                            )
                            if is_sig:
                                if cls._is_negative_literal(node.value):
                                    errors.append(
                                        "A-Share spot constraint violation: naked shorting / "
                                        "negative signal (-1) is forbidden in China equity market "
                                        "(market='cn'). Only long (1) or exit/flat (0) signals "
                                        "are permitted."
                                    )
                                elif isinstance(node.value, ast.Call):
                                    for arg in node.value.args:
                                        if cls._is_negative_literal(arg):
                                            errors.append(
                                                "A-Share spot constraint violation: "
                                                "naked shorting / negative signal (-1) is "
                                                "forbidden in China equity market (market='cn'). "
                                                "Only long (1) or exit/flat (0) signals permitted."
                                            )
                                            break
                    elif (
                        isinstance(node, ast.Return)
                        and node.value is not None
                        and cls._is_negative_literal(node.value)
                    ):
                        errors.append(
                            "A-Share spot constraint violation: returning negative signal "
                            "is forbidden in China equity market (market='cn')."
                        )
                elif (
                    enclosing == "position_sizing"
                    and isinstance(node, ast.Return)
                    and node.value is not None
                ):
                    is_neg_pos = False
                    if cls._is_negative_literal(node.value):
                        is_neg_pos = True
                    elif isinstance(node.value, ast.Call):
                        for arg in node.value.args:
                            if isinstance(arg, ast.Constant) and isinstance(
                                arg.value, (int, float, str)
                            ):
                                try:
                                    if float(arg.value) < 0:
                                        is_neg_pos = True
                                except Exception:
                                    pass
                            elif cls._is_negative_literal(arg):
                                is_neg_pos = True
                    if is_neg_pos:
                        errors.append(
                            "A-Share spot constraint violation: negative position sizing "
                            "is forbidden in China equity market (market='cn'). "
                            "Position size must be in [0.0, 1.0]."
                        )

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

    @classmethod
    def _constant_bindings(cls, tree: ast.AST) -> dict[str, float]:
        assignments: dict[str, list[ast.expr]] = {}
        mutated_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    assignments.setdefault(node.target.id, []).append(node.value)
            elif isinstance(node, (ast.AugAssign, ast.NamedExpr)) and isinstance(
                node.target, ast.Name
            ):
                mutated_names.add(node.target.id)
        bindings: dict[str, float] = {}
        for name, values in assignments.items():
            if len(values) != 1 or name in mutated_names:
                continue
            value = cls._numeric_value(values[0], {})
            if value is not None:
                bindings[name] = value
        return bindings

    @staticmethod
    def _call_argument(
        node: ast.Call, *, position: int, keywords: set[str]
    ) -> ast.expr | None:
        if len(node.args) > position:
            return node.args[position]
        for keyword in node.keywords:
            if keyword.arg in keywords:
                return keyword.value
        return None

    @staticmethod
    def _has_expanded_keywords(node: ast.Call) -> bool:
        return any(keyword.arg is None for keyword in node.keywords)

    @staticmethod
    def _is_literal_false(node: ast.expr | None) -> bool:
        return node is None or (isinstance(node, ast.Constant) and node.value is False)

    @staticmethod
    def _numeric_value(node: ast.expr | None, bindings: dict[str, float]) -> float | None:
        if node is None:
            return None
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        ):
            return float(node.value)
        if (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
        ):
            value = float(node.operand.value)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.Name):
            return bindings.get(node.id)
        return None

    @staticmethod
    def _enclosing_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current.name
            current = parents.get(current)
        return None

    @staticmethod
    def _uses_bounded_window(receiver: ast.expr) -> bool:
        for node in ast.walk(receiver):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"rolling", "expanding", "ewm"}
            ):
                return True
        return False

    @classmethod
    def _is_reverse_iloc(cls, node: ast.Subscript) -> bool:
        if not isinstance(node.value, ast.Attribute) or node.value.attr != "iloc":
            return False
        indexer = node.slice
        slices = indexer.elts if isinstance(indexer, ast.Tuple) else [indexer]
        return any(
            isinstance(item, ast.Slice)
            and item.step is not None
            and (cls._numeric_value(item.step, {}) or 0) < 0
            for item in slices
        )


@dataclass
class SelfHealResult:
    success: bool
    final_code: str
    attempts: int
    repair_logs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    strategy_digest: str = ""


class CoSteerSandbox(Protocol):
    """Execution boundary for generated strategy smoke validation."""

    def smoke_strategy(self, source_code: str) -> str | None: ...


class LocalSelfHealController:
    """Executes local self-healing for generated strategy code."""

    @classmethod
    def attempt_compile_and_heal(
        cls,
        initial_code: str,
        *,
        sandbox: CoSteerSandbox,
        repair_callback: Callable[[str, list[str]], str] | None = None,
        max_retries: int = 2,
    ) -> SelfHealResult:
        current_code = initial_code
        repair_logs: list[str] = []
        last_errors: list[str] = []

        for attempt in range(max_retries + 1):
            validation = ASTGatekeeper.validate(current_code)
            if validation.valid:
                exec_error = cls._dry_run_instantiate(current_code, sandbox=sandbox)
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
    def _dry_run_instantiate(
        source_code: str, *, sandbox: CoSteerSandbox
    ) -> str | None:
        """Submit generated code to the isolated sandbox; never execute it in the host."""
        try:
            return sandbox.smoke_strategy(source_code)
        except Exception as exc:
            return f"Isolated sandbox unavailable: {exc}"
