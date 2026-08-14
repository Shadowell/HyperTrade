"""
ARC Genetic Mutator - AST and Quality-Diversity (QD) Strategy Mutation Engine
"""

import ast
import random

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCReflexionEventV1
from hypertrade.arc.findings import (
    REMEDIATION_BY_REASON_CODE,
    ARCReasonCode,
    ParameterRemediation,
    extract_strategy_parameters,
)


class ARCGeneticMutator:
    """
    AST-level and parameter-space mutation engine for strategy code.
    Guided by negative constraints from Reflexion memory.
    """

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)

    def mutate_attempt(
        self,
        attempt: ARCCandidateAttemptV1,
        reflexion_history: list[ARCReflexionEventV1],
    ) -> ARCCandidateAttemptV1:
        """
        Produce a mutated candidate attempt with AST modifications
        and parameter tuning while respecting negative constraints.

        Two mutation pressures act together: compliance repairs move parameters the
        reviewer objected to inside their admissible bound, and an exploratory step
        resamples one other knob within the bounds the candidate itself declares. With
        repairs alone every generation converged on the same body, so successive rounds
        re-tested one strategy instead of searching.
        """
        negative_constraints: set[str] = set()
        remediations: dict[str, ParameterRemediation] = {}
        for ref in reflexion_history:
            negative_constraints.update(ref.negative_constraints)
            for raw_code in ref.reason_codes:
                remediation = _remediation_for(raw_code)
                if remediation is None:
                    continue
                # Two objections can target one parameter from opposite directions;
                # keeping the tighter repair means the mutation satisfies both.
                existing = remediations.get(remediation.parameter)
                remediations[remediation.parameter] = (
                    remediation if existing is None else _tighter(existing, remediation)
                )

        round_index = int(attempt.strategy_spec.get("mutation_round", 0)) + 1
        explored = self._pick_exploration(attempt, remediations, round_index)
        mutated_code = self._apply_ast_mutations(
            attempt.strategy_code, remediations, exploration=explored
        )

        new_attempt_id = f"att_mut{round_index}_{attempt.attempt_id[-6:]}"
        new_candidate_id = f"cand_mut{round_index}_{attempt.candidate_id[-6:]}"

        spec: dict[str, object] = {
            "parent_attempt_id": attempt.attempt_id,
            "negative_constraints_applied": sorted(negative_constraints),
            "remediated_parameters": sorted(remediations),
            "explored_parameters": sorted(explored),
            "mutation_round": round_index,
        }
        # Provenance the next generation needs to keep exploring: without the declared
        # bounds a mutated candidate has no admissible range left to resample within.
        for inherited in ("family", "direction", "parameter_bounds", "risk_overlays"):
            if inherited in attempt.strategy_spec:
                spec[inherited] = attempt.strategy_spec[inherited]

        return ARCCandidateAttemptV1(
            attempt_id=new_attempt_id,
            candidate_id=new_candidate_id,
            state="mutated",
            hypothesis=f"Mutated version of {attempt.hypothesis} with negative constraint guards",
            strategy_code=mutated_code,
            strategy_spec=spec,
        )

    def _pick_exploration(
        self,
        attempt: ARCCandidateAttemptV1,
        remediations: dict[str, ParameterRemediation],
        round_index: int,
    ) -> dict[str, float]:
        """Resample one knob the reviewer did not object to, inside its own bounds.

        Restricted to a single knob per generation so a rejection can still be
        attributed: changing the whole vector at once would leave the next verdict
        unattributable to any one dimension.
        """
        bounds = attempt.strategy_spec.get("parameter_bounds")
        if not isinstance(bounds, dict):
            return {}
        current = extract_strategy_parameters(attempt.strategy_code)
        candidates = sorted(
            name
            for name, window in bounds.items()
            if name not in remediations and isinstance(window, dict) and name in current
        )
        if not candidates:
            return {}
        # Rotate deterministically by generation so consecutive rounds probe different
        # dimensions rather than re-rolling the same one.
        name = candidates[(round_index - 1) % len(candidates)]
        window = bounds[name]
        try:
            low = float(window["min"])
            high = float(window["max"])
        except (KeyError, TypeError, ValueError):
            return {}
        if high <= low:
            return {}
        drawn = self.random.uniform(low, high)
        # Bar counts are declared as whole numbers on both the bound and the default;
        # a fractional window would be truncated by the generated clamp anyway.
        if all(value.is_integer() for value in (low, high, current[name])):
            drawn = float(round(drawn))
        if drawn == current[name]:
            drawn = high if current[name] < high else low
        return {name: drawn}

    def _apply_ast_mutations(
        self,
        code: str,
        remediations: dict[str, ParameterRemediation],
        exploration: dict[str, float] | None = None,
    ) -> str:
        """Rewrite the offending parameter declarations, preserving everything else.

        A candidate that cannot be parsed is returned untouched: emitting a partially
        repaired body would let the red team clear a candidate whose remaining logic
        was never actually reviewed.
        """
        exploration = exploration or {}
        if not remediations and not exploration:
            return code
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code
        transformer = StrategyASTTransformer(remediations=remediations, exploration=exploration)
        modified_tree = transformer.visit(tree)
        ast.fix_missing_locations(modified_tree)
        return ast.unparse(modified_tree)


def _remediation_for(raw_code: str) -> ParameterRemediation | None:
    try:
        code = ARCReasonCode(raw_code)
    except ValueError:
        return None
    return REMEDIATION_BY_REASON_CODE.get(code)


def _tighter(left: ParameterRemediation, right: ParameterRemediation) -> ParameterRemediation:
    """Pick the remediation that constrains the parameter more aggressively."""
    if left.mode is not right.mode:
        return left
    if left.mode.value == "at_most":
        return left if left.bound <= right.bound else right
    return left if left.bound >= right.bound else right


class StrategyASTTransformer(ast.NodeTransformer):
    """Rewrite numeric parameter declarations that a reviewer objected to.

    Covers both forms a candidate can declare a knob in: a module- or class-level
    literal (`stop_loss = 0.12`) and the codegen's research parameter default
    (`params.get("stop_loss", 0.12)`). Handling only the former made mutation a no-op
    on every compiled strategy.
    """

    def __init__(
        self,
        remediations: dict[str, ParameterRemediation],
        exploration: dict[str, float] | None = None,
    ):
        self.remediations = remediations
        self.exploration = exploration or {}

    def _rewrite(self, name: str, current: int | float) -> int | float | None:
        remediation = self.remediations.get(name)
        if remediation is not None:
            return _cast_like(current, remediation.repair(float(current)))
        if name in self.exploration:
            return _cast_like(current, self.exploration[name])
        return None

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        self.generic_visit(node)
        if not isinstance(node.value, ast.Constant):
            return node
        current = node.value.value
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            return node
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            replacement = self._rewrite(target.id, current)
            if replacement is not None:
                node.value = ast.Constant(value=replacement)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get" or len(node.args) != 2:
            return node
        name_node, default_node = node.args
        if not isinstance(name_node, ast.Constant) or not isinstance(name_node.value, str):
            return node
        if not isinstance(default_node, ast.Constant):
            return node
        current = default_node.value
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            return node
        replacement = self._rewrite(name_node.value, current)
        if replacement is None:
            return node
        node.args = [name_node, ast.Constant(value=replacement)]
        return node


def _cast_like(original: int | float, repaired: float) -> int | float:
    """Keep integral knobs integral so generated `int(...)` clamps stay meaningful."""
    if isinstance(original, int):
        return int(round(repaired))
    return round(repaired, 6)
