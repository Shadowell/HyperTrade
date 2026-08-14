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

        mutated_code = self._apply_ast_mutations(attempt.strategy_code, remediations)

        new_attempt_id = f"att_mut_{attempt.attempt_id[-6:]}"
        new_candidate_id = f"cand_mut_{attempt.candidate_id[-6:]}"

        return ARCCandidateAttemptV1(
            attempt_id=new_attempt_id,
            candidate_id=new_candidate_id,
            state="mutated",
            hypothesis=f"Mutated version of {attempt.hypothesis} with negative constraint guards",
            strategy_code=mutated_code,
            strategy_spec={
                "parent_attempt_id": attempt.attempt_id,
                "negative_constraints_applied": sorted(negative_constraints),
                "remediated_parameters": sorted(remediations),
                "mutation_round": attempt.strategy_spec.get("mutation_round", 0) + 1,
            },
        )

    def _apply_ast_mutations(
        self,
        code: str,
        remediations: dict[str, ParameterRemediation],
    ) -> str:
        """Rewrite the offending parameter declarations, preserving everything else.

        A candidate that cannot be parsed is returned untouched: emitting a partially
        repaired body would let the red team clear a candidate whose remaining logic
        was never actually reviewed.
        """
        if not remediations:
            return code
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return code
        transformer = StrategyASTTransformer(remediations=remediations)
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

    def __init__(self, remediations: dict[str, ParameterRemediation]):
        self.remediations = remediations

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
            remediation = self.remediations.get(target.id)
            if remediation is None:
                continue
            node.value = ast.Constant(value=_cast_like(current, remediation.repair(float(current))))
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
        remediation = self.remediations.get(name_node.value)
        if remediation is None:
            return node
        repaired = _cast_like(current, remediation.repair(float(current)))
        node.args = [name_node, ast.Constant(value=repaired)]
        return node


def _cast_like(original: int | float, repaired: float) -> int | float:
    """Keep integral knobs integral so generated `int(...)` clamps stay meaningful."""
    if isinstance(original, int):
        return int(round(repaired))
    return round(repaired, 6)
