"""Parameter search space models, AST extraction, and mutation samplers."""

from __future__ import annotations

import ast
import asyncio
import itertools
import json
import math
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


class ParameterSpec(ABC):
    """Abstract base class for a tunable hyperparameter."""

    name: str

    @abstractmethod
    def sample(self, rng: random.Random) -> Any: ...

    @abstractmethod
    def grid(self, points: int = 5) -> list[Any]: ...

    @abstractmethod
    def perturb(self, val: Any, ratio: float, rng: random.Random) -> Any: ...

    @abstractmethod
    def validate_value(self, val: Any) -> bool: ...

    @abstractmethod
    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> ParameterSpec: ...


@dataclass(frozen=True)
class IntParam(ParameterSpec):
    name: str
    min_val: int
    max_val: int
    step: int = 1
    default: int | None = None

    def __post_init__(self) -> None:
        if self.min_val > self.max_val:
            raise ValueError(f"IntParam {self.name}: min {self.min_val} > max {self.max_val}")
        if self.step < 1:
            raise ValueError(f"IntParam {self.name}: step must be >= 1, got {self.step}")

    def sample(self, rng: random.Random) -> int:
        steps = (self.max_val - self.min_val) // self.step
        return self.min_val + rng.randint(0, steps) * self.step

    def grid(self, points: int = 5) -> list[int]:
        values = list(range(self.min_val, self.max_val + 1, self.step))
        if len(values) <= points:
            return values
        # Uniformly pick points
        step_idx = (len(values) - 1) / (points - 1)
        chosen_indices = sorted({round(i * step_idx) for i in range(points)})
        return [values[idx] for idx in chosen_indices]

    def perturb(self, val: int, ratio: float, rng: random.Random) -> int:
        delta = max(self.step, round(abs(val) * ratio))
        direction = rng.choice([-1, 1])
        new_val = val + direction * delta
        clamped = max(self.min_val, min(self.max_val, new_val))
        # Snap to step
        snapped = self.min_val + round((clamped - self.min_val) / self.step) * self.step
        return max(self.min_val, min(self.max_val, snapped))

    def validate_value(self, val: Any) -> bool:
        if not isinstance(val, int) or isinstance(val, bool):
            return False
        if not (self.min_val <= val <= self.max_val):
            return False
        return (val - self.min_val) % self.step == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "int",
            "name": self.name,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "step": self.step,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntParam:
        return cls(
            name=data["name"],
            min_val=int(data["min_val"]),
            max_val=int(data["max_val"]),
            step=int(data.get("step", 1)),
            default=int(data["default"]) if data.get("default") is not None else None,
        )


@dataclass(frozen=True)
class FloatParam(ParameterSpec):
    name: str
    min_val: float
    max_val: float
    step: float | None = None
    scale: str = "linear"  # "linear" or "log"
    default: float | None = None

    def __post_init__(self) -> None:
        if self.min_val > self.max_val:
            raise ValueError(f"FloatParam {self.name}: min {self.min_val} > max {self.max_val}")
        if self.scale == "log" and self.min_val <= 0:
            raise ValueError(
                f"FloatParam {self.name}: log scale requires min > 0, got {self.min_val}"
            )

    def sample(self, rng: random.Random) -> float:
        if self.scale == "log":
            log_min = math.log(self.min_val)
            log_max = math.log(self.max_val)
            raw = math.exp(rng.uniform(log_min, log_max))
        else:
            raw = rng.uniform(self.min_val, self.max_val)

        if self.step is not None and self.step > 0:
            steps = round((raw - self.min_val) / self.step)
            raw = self.min_val + steps * self.step
            raw = max(self.min_val, min(self.max_val, raw))
        return round(raw, 6)

    def grid(self, points: int = 5) -> list[float]:
        points = max(2, points)
        if self.scale == "log":
            log_min = math.log(self.min_val)
            log_max = math.log(self.max_val)
            step_size = (log_max - log_min) / (points - 1)
            vals = [round(math.exp(log_min + i * step_size), 6) for i in range(points)]
        else:
            step_size = (self.max_val - self.min_val) / (points - 1)
            vals = [round(self.min_val + i * step_size, 6) for i in range(points)]

        if self.step is not None and self.step > 0:
            snapped = []
            for val in vals:
                k = round((val - self.min_val) / self.step)
                snapped_val = max(self.min_val, min(self.max_val, self.min_val + k * self.step))
                snapped.append(round(snapped_val, 6))
            vals = sorted(set(snapped))
        return vals

    def perturb(self, val: float, ratio: float, rng: random.Random) -> float:
        delta = max(self.step or 1e-4, abs(val) * ratio)
        direction = rng.choice([-1.0, 1.0])
        new_val = val + direction * delta
        clamped = max(self.min_val, min(self.max_val, new_val))
        if self.step is not None and self.step > 0:
            k = round((clamped - self.min_val) / self.step)
            clamped = max(self.min_val, min(self.max_val, self.min_val + k * self.step))
        return round(clamped, 6)

    def validate_value(self, val: Any) -> bool:
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return False
        val_f = float(val)
        return bool(self.min_val - 1e-9 <= val_f <= self.max_val + 1e-9)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "float",
            "name": self.name,
            "min_val": self.min_val,
            "max_val": self.max_val,
            "step": self.step,
            "scale": self.scale,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FloatParam:
        return cls(
            name=data["name"],
            min_val=float(data["min_val"]),
            max_val=float(data["max_val"]),
            step=float(data["step"]) if data.get("step") is not None else None,
            scale=data.get("scale", "linear"),
            default=float(data["default"]) if data.get("default") is not None else None,
        )


@dataclass(frozen=True)
class CategoricalParam(ParameterSpec):
    name: str
    choices: list[Any]
    default: Any | None = None

    def __post_init__(self) -> None:
        if not self.choices:
            raise ValueError(f"CategoricalParam {self.name}: choices cannot be empty")

    def sample(self, rng: random.Random) -> Any:
        return rng.choice(self.choices)

    def grid(self, points: int = 5) -> list[Any]:
        return list(self.choices)

    def perturb(self, val: Any, ratio: float, rng: random.Random) -> Any:
        other_choices = [c for c in self.choices if c != val]
        return rng.choice(other_choices) if other_choices else val

    def validate_value(self, val: Any) -> bool:
        return val in self.choices

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "categorical",
            "name": self.name,
            "choices": self.choices,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CategoricalParam:
        return cls(
            name=data["name"],
            choices=data["choices"],
            default=data.get("default"),
        )


@dataclass
class ConstraintRule:
    """Logical rule to constrain combinations of parameters."""

    expression: str
    validator: Callable[[dict[str, Any]], bool] | None = None

    def evaluate(self, params: dict[str, Any]) -> bool:
        if self.validator is not None:
            return bool(self.validator(params))
        # Simple safe expression evaluator for expressions like "fast_period < slow_period"
        try:
            return bool(eval(self.expression, {"__builtins__": {}}, dict(params)))  # nosec B307
        except Exception:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {"expression": self.expression}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstraintRule:
        return cls(expression=data["expression"])


class ParameterSpace:
    """Multi-dimensional hyperparameter search space with constraints."""

    def __init__(
        self,
        parameters: Sequence[ParameterSpec] | None = None,
        constraints: Sequence[ConstraintRule] | None = None,
    ) -> None:
        self.parameters: dict[str, ParameterSpec] = {}
        for p in parameters or []:
            self.add_param(p)
        self.constraints: list[ConstraintRule] = list(constraints or [])

    def add_param(self, param: ParameterSpec) -> None:
        self.parameters[param.name] = param

    def add_constraint(self, rule: ConstraintRule) -> None:
        self.constraints.append(rule)

    def validate(self, params: dict[str, Any]) -> tuple[bool, str]:
        for name, spec in self.parameters.items():
            if name not in params:
                return False, f"Missing parameter: {name}"
            if not spec.validate_value(params[name]):
                return False, f"Invalid value for {name}: {params[name]}"

        for rule in self.constraints:
            if not rule.evaluate(params):
                return False, f"Violated constraint: {rule.expression}"
        return True, ""

    def sample_random(
        self,
        rng: random.Random | None = None,
        max_attempts: int = 100,
    ) -> dict[str, Any]:
        rng = rng or random.Random()
        for _ in range(max_attempts):
            candidate = {name: spec.sample(rng) for name, spec in self.parameters.items()}
            valid, _ = self.validate(candidate)
            if valid:
                return candidate
        # If random sampling hits constraint wall, return candidate ignoring constraints as fallback
        return {name: spec.sample(rng) for name, spec in self.parameters.items()}

    def generate_grid(
        self,
        points_per_param: int = 4,
        max_combinations: int = 120,
    ) -> list[dict[str, Any]]:
        names = list(self.parameters.keys())
        if not names:
            return [{}]
        lists = [self.parameters[name].grid(points_per_param) for name in names]
        cartesian = itertools.product(*lists)

        results: list[dict[str, Any]] = []
        for combo in cartesian:
            candidate = dict(zip(names, combo, strict=True))
            valid, _ = self.validate(candidate)
            if valid:
                results.append(candidate)
            if len(results) >= max_combinations:
                break
        return results

    def perturb(
        self,
        params: dict[str, Any],
        ratio: float = 0.1,
        rng: random.Random | None = None,
        max_attempts: int = 50,
    ) -> dict[str, Any]:
        rng = rng or random.Random()
        for _ in range(max_attempts):
            perturbed: dict[str, Any] = {}
            for name, spec in self.parameters.items():
                val = params.get(name)
                if val is not None:
                    perturbed[name] = spec.perturb(val, ratio, rng)
                else:
                    perturbed[name] = spec.sample(rng)
            valid, _ = self.validate(perturbed)
            if valid and perturbed != params:
                return perturbed
        return dict(params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "parameters": [p.to_dict() for p in self.parameters.values()],
            "constraints": [c.to_dict() for c in self.constraints],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ParameterSpace:
        space = cls()
        for p_data in data.get("parameters", []):
            p_type = p_data.get("type")
            if p_type == "int":
                space.add_param(IntParam.from_dict(p_data))
            elif p_type == "float":
                space.add_param(FloatParam.from_dict(p_data))
            elif p_type == "categorical":
                space.add_param(CategoricalParam.from_dict(p_data))
        for c_data in data.get("constraints", []):
            space.add_constraint(ConstraintRule.from_dict(c_data))
        return space


def extract_parameter_space_from_code(code: str) -> ParameterSpace:
    """Parse strategy AST and extract tunable parameter space with sensible ranges."""
    space = ParameterSpace()
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return space

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check __init__ arguments and default values
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    args = item.args.args[1:]  # skip self
                    defaults = item.args.defaults
                    # Defaults are right-aligned
                    num_defaults = len(defaults)
                    num_args = len(args)
                    for i, arg in enumerate(args):
                        default_idx = i - (num_args - num_defaults)
                        default_val: Any = None
                        if default_idx >= 0:
                            default_node = defaults[default_idx]
                            default_val = _extract_literal_val(default_node)

                        name = arg.arg
                        if name in {"config", "args", "kwargs", "symbols", "venue", "broker"}:
                            continue

                        # Determine type and range
                        if isinstance(default_val, int) and not isinstance(default_val, bool):
                            min_val = max(1, int(default_val * 0.4))
                            max_val = max(min_val + 2, int(default_val * 2.5))
                            space.add_param(
                                IntParam(name, min_val, max_val, step=1, default=default_val)
                            )
                        elif isinstance(default_val, float):
                            min_flt = round(max(1e-4, default_val * 0.4), 6)
                            max_flt = round(default_val * 2.5, 6)
                            space.add_param(FloatParam(name, min_flt, max_flt, default=default_val))

                # Check config.get("param", default) calls in methods
                elif isinstance(item, ast.FunctionDef):
                    for subnode in ast.walk(item):
                        if (
                            isinstance(subnode, ast.Call)
                            and isinstance(subnode.func, ast.Attribute)
                            and subnode.func.attr == "get"
                            and len(subnode.args) >= 2
                        ):
                            key_node = subnode.args[0]
                            val_node = subnode.args[1]
                            key = _extract_literal_val(key_node)
                            val = _extract_literal_val(val_node)
                            if isinstance(key, str) and key not in space.parameters:
                                if isinstance(val, int) and not isinstance(val, bool):
                                    min_v = max(1, int(val * 0.5))
                                    max_v = max(min_v + 2, int(val * 2.5))
                                    space.add_param(IntParam(key, min_v, max_v, default=val))
                                elif isinstance(val, float):
                                    min_v_flt = round(max(1e-4, val * 0.5), 6)
                                    max_v_flt = round(val * 2.5, 6)
                                    space.add_param(
                                        FloatParam(key, min_v_flt, max_v_flt, default=val)
                                    )

    # Add common heuristic constraints
    if "fast_period" in space.parameters and "slow_period" in space.parameters:
        space.add_constraint(ConstraintRule("fast_period < slow_period"))
    if "fast_ma" in space.parameters and "slow_ma" in space.parameters:
        space.add_constraint(ConstraintRule("fast_ma < slow_ma"))
    if "short_window" in space.parameters and "long_window" in space.parameters:
        space.add_constraint(ConstraintRule("short_window < long_window"))

    return space


def _extract_literal_val(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    ):
        return -node.operand.value
    return None


class GridSampler:
    """Generates trials on a deterministic grid."""

    def __init__(self, space: ParameterSpace, points_per_param: int = 3) -> None:
        self.space = space
        self.points_per_param = points_per_param

    def sample_all(self, max_trials: int = 100) -> list[dict[str, Any]]:
        return self.space.generate_grid(
            points_per_param=self.points_per_param,
            max_combinations=max_trials,
        )


class RandomSampler:
    """Generates trials via independent random draws."""

    def __init__(self, space: ParameterSpace, seed: int | None = None) -> None:
        self.space = space
        self.rng = random.Random(seed)

    def sample_n(self, n: int) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        seen: set[str] = set()
        for _ in range(n * 3):
            cand = self.space.sample_random(self.rng)
            key = json.dumps(cand, sort_keys=True)
            if key not in seen:
                seen.add(key)
                samples.append(cand)
            if len(samples) >= n:
                break
        return samples


class LlmMutationSampler:
    """Generates focused parameter mutations using LLM reasoning based on past trial outcomes."""

    def __init__(self, space: ParameterSpace, seed: int | None = None) -> None:
        self.space = space
        self.rng = random.Random(seed)

    async def mutate(
        self,
        *,
        current_best: dict[str, Any] | None,
        top_trials: Sequence[dict[str, Any]],
        worst_trials: Sequence[dict[str, Any]],
        n_mutations: int = 5,
        chat_provider: Any = None,
    ) -> list[dict[str, Any]]:
        """Propose parameter mutations informed by top and worst historical trials."""
        # If no chat provider or no history, fall back to perturbation around best or random
        if chat_provider is None or (not current_best and not top_trials):
            return self._fallback_mutations(current_best, n_mutations)

        system_prompt = (
            "You are an expert quantitative trading researcher specializing in parameter tuning.\n"
            "Analyze the parameter search space and backtest performance differences "
            "between top-performing trials and worst-performing trials.\n"
            "Propose new parameter candidates that explore promising regions, refine the best "
            "settings, and escape overfitting traps.\n"
            "Respond ONLY with a JSON array of parameter dictionaries matching specifications."
        )

        user_content = json.dumps(
            {
                "parameter_space": self.space.to_dict(),
                "current_best": current_best,
                "top_performing_trials": list(top_trials[:3]),
                "worst_performing_trials": list(worst_trials[:2]),
                "desired_mutation_count": n_mutations,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]
            call_res = chat_provider.chat(messages)
            if asyncio.iscoroutine(call_res):
                resp = await call_res
            else:
                resp = call_res

            if hasattr(resp, "content"):
                raw = str(resp.content).strip()
            elif isinstance(resp, dict) and "content" in resp:
                raw = str(resp["content"]).strip()
            elif isinstance(resp, str):
                raw = resp.strip()
            else:
                raw = str(resp).strip()

            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                valid_candidates: list[dict[str, Any]] = []
                for item in parsed:
                    if isinstance(item, dict):
                        valid, _ = self.space.validate(item)
                        if valid:
                            valid_candidates.append(item)
                if valid_candidates:
                    # Fill up if needed
                    while len(valid_candidates) < n_mutations:
                        perturbed = self.space.perturb(valid_candidates[0], rng=self.rng)
                        valid_candidates.append(perturbed)
                    return valid_candidates[:n_mutations]
        except Exception:
            pass

        return self._fallback_mutations(current_best, n_mutations)

    def _fallback_mutations(
        self,
        base_params: dict[str, Any] | None,
        n_mutations: int,
    ) -> list[dict[str, Any]]:
        mutations: list[dict[str, Any]] = []
        base = base_params or self.space.sample_random(self.rng)
        for _ in range(n_mutations):
            mutated = self.space.perturb(base, ratio=self.rng.uniform(0.05, 0.25), rng=self.rng)
            mutations.append(mutated)
        return mutations
