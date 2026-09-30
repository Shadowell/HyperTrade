"""Freeform strategy synthesis and AST sandbox verification.

Enables autonomous trading agents and researchers to synthesize and test
arbitrary BaseStrategy logic beyond the 7 fixed templates, while enforcing
strict AST sandbox security and in-memory execution dry-runs.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import types
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hypertrade.research.codegen import (
    generate_strategy,
    static_code_rejections,
)


@dataclass(frozen=True)
class FreeformValidationResult:
    is_valid: bool
    rejections: list[str]
    class_name: str = ""
    discovered_parameters: dict[str, Any] = field(default_factory=dict)
    methods_defined: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SmokeTestResult:
    passed: bool
    bars_processed: int
    orders_simulated: int
    error: str = ""


@dataclass(frozen=True)
class SynthesizedStrategy:
    code: str
    class_name: str
    is_freeform: bool
    tunable_parameters: dict[str, Any]
    validation: FreeformValidationResult
    smoke_test: SmokeTestResult


class MockBroker:
    def __init__(self, equity: float = 10000.0) -> None:
        self.equity = equity


class MockBarData:
    def __init__(
        self,
        symbol: str,
        close_price: float,
        open_price: float | None = None,
        high_price: float | None = None,
        low_price: float | None = None,
        volume: float = 100.0,
    ) -> None:
        self.symbol = symbol
        self.close_price = close_price
        self.close = close_price
        self.open_price = open_price if open_price is not None else close_price
        self.high_price = high_price if high_price is not None else close_price * 1.01
        self.low_price = low_price if low_price is not None else close_price * 0.99
        self.volume = volume


class MockBaseStrategy:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.broker = MockBroker()
        self.orders: list[dict[str, Any]] = []

    def symbols(self) -> list[str]:
        return ["BTC-USDT-SWAP"]

    async def open_contract(
        self,
        symbol: str,
        direction: str,
        volume: float,
        order_type: str = "market",
        price: float | None = None,
    ) -> dict[str, Any]:
        order = {
            "action": "open",
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "order_type": order_type,
            "price": price,
        }
        self.orders.append(order)
        return {"status": "ok", "order": order}

    async def close_contract(
        self,
        symbol: str,
        direction: str,
        volume: float,
        order_type: str = "market",
        price: float | None = None,
    ) -> dict[str, Any]:
        order = {
            "action": "close",
            "symbol": symbol,
            "direction": direction,
            "volume": volume,
            "order_type": order_type,
            "price": price,
        }
        self.orders.append(order)
        return {"status": "ok", "order": order}

    async def get_contract_position(
        self,
        symbol: str,
        direction: str = "long",
    ) -> dict[str, Any] | None:
        return None

    async def on_init(self) -> None:
        pass

    async def on_bar(self, bar: Any) -> None:
        pass


class _ASTParameterVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self.methods: list[str] = []
        self.class_name: str = ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not self.class_name:
            self.class_name = node.name
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.methods.append(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.methods.append(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr.startswith("p_")
            ):
                param_name = target.attr[2:]
                val: Any = None
                if isinstance(node.value, ast.Constant):
                    val = node.value.value
                self.params[param_name] = val
        self.generic_visit(node)


class FreeformStrategySynthesizer:
    """Synthesizes, validates, and smoke-tests freeform and templated strategies."""

    def validate_code(self, code: str) -> FreeformValidationResult:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return FreeformValidationResult(
                is_valid=False,
                rejections=[f"invalid_python_syntax:{exc.lineno}"],
            )

        rejections = static_code_rejections(code)
        visitor = _ASTParameterVisitor()
        visitor.visit(tree)

        return FreeformValidationResult(
            is_valid=len(rejections) == 0,
            rejections=rejections,
            class_name=visitor.class_name,
            discovered_parameters=visitor.params,
            methods_defined=visitor.methods,
        )

    def dry_run(self, code: str, bars_count: int = 10) -> SmokeTestResult:
        validation = self.validate_code(code)
        if not validation.is_valid:
            return SmokeTestResult(
                passed=False,
                bars_processed=0,
                orders_simulated=0,
                error=f"validation_failed:{','.join(validation.rejections)}",
            )

        # Build isolated sandbox namespace with mocked app.core modules
        fake_module_name = "app.core.execution.base_strategy"
        created_modules: list[str] = []
        for mod in ["app", "app.core", "app.core.execution", fake_module_name]:
            if mod not in sys.modules:
                sys.modules[mod] = types.ModuleType(mod)
                created_modules.append(mod)

        target_mod = sys.modules[fake_module_name]
        target_mod.BaseStrategy = MockBaseStrategy  # type: ignore[attr-defined]
        target_mod.BarData = MockBarData  # type: ignore[attr-defined]

        import builtins

        def safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            allowed_top_levels = {
                "collections",
                "math",
                "statistics",
                "datetime",
                "typing",
                "dataclasses",
                "app",
            }
            top_level = name.split(".")[0]
            if top_level not in allowed_top_levels:
                raise ImportError(f"Import of {name} is blocked in sandbox")
            return builtins.__import__(name, *args, **kwargs)

        safe_builtins = dict(builtins.__dict__)
        for blocked in ("eval", "exec", "open", "input", "breakpoint"):
            safe_builtins.pop(blocked, None)
        safe_builtins["__import__"] = safe_import

        sandbox_env: dict[str, Any] = {
            "__builtins__": safe_builtins,
            "deque": deque,
            "BaseStrategy": MockBaseStrategy,
            "BarData": MockBarData,
        }

        try:
            exec(code, sandbox_env)  # noqa: S102
            strategy_cls = sandbox_env.get(validation.class_name)
            if not strategy_cls or not isinstance(strategy_cls, type):
                return SmokeTestResult(
                    passed=False,
                    bars_processed=0,
                    orders_simulated=0,
                    error=f"class_{validation.class_name}_not_found",
                )

            instance = strategy_cls(config={})
            if hasattr(instance, "on_init"):
                init_res = instance.on_init()
                if asyncio.iscoroutine(init_res):
                    asyncio.run(init_res)

            processed = 0
            for i in range(bars_count):
                price = 60000.0 + (i * 100.0 if i % 2 == 0 else -i * 50.0)
                bar = MockBarData(symbol="BTC-USDT-SWAP", close_price=price)
                bar_res = instance.on_bar(bar)
                if asyncio.iscoroutine(bar_res):
                    asyncio.run(bar_res)
                processed += 1

            orders_count = len(getattr(instance, "orders", []))
            return SmokeTestResult(
                passed=True,
                bars_processed=processed,
                orders_simulated=orders_count,
            )
        except Exception as exc:
            return SmokeTestResult(
                passed=False,
                bars_processed=0,
                orders_simulated=0,
                error=f"runtime_error:{exc}",
            )
        finally:
            for mod in reversed(created_modules):
                sys.modules.pop(mod, None)

    def synthesize(
        self,
        *,
        spec: Mapping[str, Any] | None = None,
        custom_code: str | None = None,
    ) -> SynthesizedStrategy:
        if custom_code is not None:
            validation = self.validate_code(custom_code)
            smoke = self.dry_run(custom_code) if validation.is_valid else SmokeTestResult(
                passed=False,
                bars_processed=0,
                orders_simulated=0,
                error="validation_failed",
            )
            return SynthesizedStrategy(
                code=custom_code,
                class_name=validation.class_name,
                is_freeform=True,
                tunable_parameters=validation.discovered_parameters,
                validation=validation,
                smoke_test=smoke,
            )

        if spec is not None:
            generated = generate_strategy(spec)
            validation = self.validate_code(generated.code)
            smoke = self.dry_run(generated.code)
            return SynthesizedStrategy(
                code=generated.code,
                class_name=generated.class_name,
                is_freeform=False,
                tunable_parameters=generated.tunable_parameters,
                validation=validation,
                smoke_test=smoke,
            )

        raise ValueError("Either spec or custom_code must be provided")
