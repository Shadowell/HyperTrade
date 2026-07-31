"""
HyperARC Main Solver Engine for ARC-AGI-3 (ARC Prize 2026)
"""

from collections.abc import Callable
from typing import Any

from hypertrade.arc_agi.dsl import GridDSL
from hypertrade.hyperarc.harness import HyperARCHarness
from hypertrade.hyperarc.mcts import HyperARCParallelMCTSEngine


def _make_crop_fn(bg: int) -> Callable[[list[list[int]]], list[list[int]]]:
    def _crop(g: list[list[int]]) -> list[list[int]]:
        return GridDSL.crop_bounding_box(g, bg)
    return _crop


class HyperARCSolver:
    """
    Main HyperARC AGI Program Synthesis Solver.
    Integrates Parallel MCTS, Grid DSL, and Self-Healing Harness.
    """

    def __init__(self, parallel_workers: int = 4) -> None:
        self.mcts_engine = HyperARCParallelMCTSEngine(parallel_workers=parallel_workers)

    def solve(
        self, train_examples: list[dict[str, Any]], test_input: list[list[int]]
    ) -> list[list[int]]:
        candidate_ops: list[tuple[str, dict[str, Any]]] = [
            ("rotate_90", {}),
            ("flip_horizontal", {}),
            ("crop", {"bg": 0}),
            ("replace_color", {"old": 1, "new": 2}),
        ]

        def _evaluate_pipeline(pipeline: list[tuple[str, dict[str, Any]]]) -> float:
            matches = 0
            for ex in train_examples:
                inp = ex.get("input", [])
                out = ex.get("output", [])
                pred = inp
                for op_name, p in pipeline:
                    if op_name == "rotate_90":
                        pred = HyperARCHarness.safe_apply_grid_op(GridDSL.rotate_90, pred)
                    elif op_name == "flip_horizontal":
                        pred = HyperARCHarness.safe_apply_grid_op(GridDSL.flip_horizontal, pred)
                    elif op_name == "crop":
                        bg_val = p.get("bg", 0)
                        pred = HyperARCHarness.safe_apply_grid_op(_make_crop_fn(bg_val), pred)
                if GridDSL.match_grids(pred, out):
                    matches += 1
            return matches / len(train_examples) if train_examples else 0.0

        best_pipeline = self.mcts_engine.search_best_program(candidate_ops, _evaluate_pipeline)

        res = test_input
        for op_name, p in best_pipeline:
            if op_name == "rotate_90":
                res = HyperARCHarness.safe_apply_grid_op(GridDSL.rotate_90, res)
            elif op_name == "flip_horizontal":
                res = HyperARCHarness.safe_apply_grid_op(GridDSL.flip_horizontal, res)
            elif op_name == "crop":
                bg_val = p.get("bg", 0)
                res = HyperARCHarness.safe_apply_grid_op(_make_crop_fn(bg_val), res)
        return res
