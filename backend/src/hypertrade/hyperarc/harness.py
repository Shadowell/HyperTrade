"""
HyperARC Self-Healing Program Execution Harness
Derived from HyperTrade Industrial Agent Scaffolding.
"""

from collections.abc import Callable


class HyperARCHarness:
    """
    Self-healing Program Execution Harness for HyperARC.
    Intercepts grid transformation errors and executes self-repair logic.
    """

    @staticmethod
    def safe_apply_grid_op(
        op_fn: Callable[[list[list[int]]], list[list[int]]],
        grid: list[list[int]],
        fallback_grid: list[list[int]] | None = None,
    ) -> list[list[int]]:
        try:
            res = op_fn(grid)
            if not res or not isinstance(res, list):
                return fallback_grid if fallback_grid is not None else grid
            return res
        except Exception:
            return fallback_grid if fallback_grid is not None else grid
