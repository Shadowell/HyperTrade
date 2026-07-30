"""
ARC Genetic Mutator - AST and Quality-Diversity (QD) Strategy Mutation Engine
"""

import ast
import random

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCReflexionEventV1


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
        for ref in reflexion_history:
            negative_constraints.update(ref.negative_constraints)

        original_code = attempt.strategy_code
        mutated_code = self._apply_ast_mutations(original_code, negative_constraints)

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
                "negative_constraints_applied": list(negative_constraints),
                "mutation_round": attempt.strategy_spec.get("mutation_round", 0) + 1,
            },
        )

    def _apply_ast_mutations(self, code: str, constraints: set[str]) -> str:
        """
        Parse Python code into AST, perform targeted assignment AST mutations.
        """
        try:
            tree = ast.parse(code)
            transformer = StrategyASTTransformer(constraints=constraints)
            modified_tree = transformer.visit(tree)
            ast.fix_missing_locations(modified_tree)
            return ast.unparse(modified_tree)
        except Exception:
            guard_comment = f"# Guarded constraints: {list(constraints)}\n"
            return guard_comment + code.replace("stop_loss = 0.12", "stop_loss = 0.08")


class StrategyASTTransformer(ast.NodeTransformer):
    """
    AST transformer to mutate specific parameter assignments based on negative constraints.
    """

    def __init__(self, constraints: set[str]):
        self.constraints = constraints

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        self.generic_visit(node)
        # Check target variable name in assignment statement
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                if var_name == "stop_loss" and any(
                    "stop_loss" in c.lower() or "止损" in c for c in self.constraints
                ):
                    # Replace assignment constant value with safe 0.08
                    node.value = ast.Constant(value=0.08)
        return node
