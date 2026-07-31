"""
HyperARC Parallel MCTS Program Synthesis Engine
Derived from HyperTrade Parallel MCTS Architecture.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HyperARCNode:
    program_ops: list[tuple[str, dict[str, Any]]]
    visits: int = 0
    total_reward: float = 0.0
    children: list["HyperARCNode"] = field(default_factory=list)

    @property
    def mean_reward(self) -> float:
        return self.total_reward / self.visits if self.visits > 0 else 0.0


class HyperARCParallelMCTSEngine:
    """
    Parallel MCTS Rollout Engine for Program Synthesis in HyperARC.
    """

    def __init__(self, parallel_workers: int = 4) -> None:
        self.parallel_workers = parallel_workers

    def search_best_program(
        self,
        candidate_ops: list[tuple[str, dict[str, Any]]],
        eval_fn: Callable[[list[tuple[str, dict[str, Any]]]], float],
        max_rollouts: int = 20,
    ) -> list[tuple[str, dict[str, Any]]]:
        def _rollout_worker(
            op: tuple[str, dict[str, Any]]
        ) -> tuple[list[tuple[str, dict[str, Any]]], float]:
            pipeline = [op]
            reward = eval_fn(pipeline)
            return pipeline, reward

        best_program: list[tuple[str, dict[str, Any]]] = []
        best_score = -1.0

        with ThreadPoolExecutor(max_workers=min(len(candidate_ops), self.parallel_workers)) as ex:
            futures = [ex.submit(_rollout_worker, op) for op in candidate_ops[:max_rollouts]]
            for fut in futures:
                try:
                    pipeline, reward = fut.result()
                    if reward > best_score:
                        best_score = reward
                        best_program = pipeline
                except Exception:
                    pass

        return best_program
