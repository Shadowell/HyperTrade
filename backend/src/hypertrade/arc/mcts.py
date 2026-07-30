"""
ARC MCTS (Monte Carlo Tree Search) & MAP-Elites Quality-Diversity Grid Engine
"""

import math

from pydantic import BaseModel, Field

from hypertrade.arc.contracts import ARCCandidateAttemptV1


class MCTSNode(BaseModel):
    node_id: str
    attempt: ARCCandidateAttemptV1
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    visits: int = 0
    total_value: float = 0.0
    depth: int = 0
    feature_descriptor: tuple[str, str] = Field(
        default=("medium_term", "ranging")
    )

    @property
    def mean_value(self) -> float:
        return self.total_value / self.visits if self.visits > 0 else 0.0

    def ucb1_score(
        self, parent_visits: int, exploration_weight: float = 1.414
    ) -> float:
        if self.visits == 0:
            return float("inf")
        exploitation = self.mean_value
        exploration = exploration_weight * math.sqrt(
            math.log(parent_visits) / self.visits
        )
        return exploitation + exploration


class MAPElitesGrid:
    """
    Quality-Diversity (QD) grid archive preserving elite strategy nodes
    across multi-dimensional feature spaces (e.g. Horizon x Regime).
    """

    def __init__(self) -> None:
        # Archive mapping (horizon_bucket, regime_bucket) -> MCTSNode
        self.archive: dict[tuple[str, str], MCTSNode] = {}

    def get_feature_descriptor(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[str, str]:
        code = attempt.strategy_code
        metrics = attempt.observed_metrics

        # Determine holding horizon bucket
        if "lookback_period = 5" in code or "lookback_period = 10" in code:
            horizon = "short_term"
        elif "lookback_period = 50" in code or "lookback_period = 100" in code:
            horizon = "long_term"
        else:
            horizon = "medium_term"

        # Determine regime fit bucket based on metrics or strategy type
        sharpe = metrics.get("sharpe_after_attack", 0.0)
        if sharpe > 1.5:
            regime = "trending_strong"
        elif sharpe > 1.0:
            regime = "ranging_moderate"
        else:
            regime = "defensive_low_vol"

        return (horizon, regime)

    def add_candidate(self, node: MCTSNode) -> bool:
        """
        Add node to QD Archive if cell is empty or if node outperforms existing elite.
        Returns: True if elite archive was updated.
        """
        cell_key = node.feature_descriptor
        if cell_key not in self.archive:
            self.archive[cell_key] = node
            return True

        existing_elite = self.archive[cell_key]
        if node.mean_value > existing_elite.mean_value:
            self.archive[cell_key] = node
            return True

        return False

    def get_elites(self) -> list[MCTSNode]:
        return list(self.archive.values())


class ARCMCTSEngine:
    """
    Monte Carlo Tree Search Engine managing strategy exploration tree and UCB1 selection.
    """

    def __init__(self, exploration_weight: float = 1.414) -> None:
        self.nodes: dict[str, MCTSNode] = {}
        self.root_id: str | None = None
        self.exploration_weight = exploration_weight
        self.qd_grid = MAPElitesGrid()

    def add_root(self, attempt: ARCCandidateAttemptV1) -> MCTSNode:
        descriptor = self.qd_grid.get_feature_descriptor(attempt)
        node = MCTSNode(
            node_id=attempt.attempt_id,
            attempt=attempt,
            feature_descriptor=descriptor,
        )
        self.nodes[node.node_id] = node
        self.root_id = node.node_id
        self.qd_grid.add_candidate(node)
        return node

    def add_child(
        self, parent_id: str, attempt: ARCCandidateAttemptV1
    ) -> MCTSNode:
        parent = self.nodes.get(parent_id)
        descriptor = self.qd_grid.get_feature_descriptor(attempt)
        node = MCTSNode(
            node_id=attempt.attempt_id,
            attempt=attempt,
            parent_id=parent_id,
            depth=(parent.depth + 1) if parent else 0,
            feature_descriptor=descriptor,
        )
        self.nodes[node.node_id] = node
        if parent:
            parent.children_ids.append(node.node_id)
        self.qd_grid.add_candidate(node)
        return node

    def select_best_node_to_expand(self) -> MCTSNode | None:
        if not self.nodes:
            return None

        current = (
            self.nodes.get(self.root_id)
            if self.root_id
            else list(self.nodes.values())[0]
        )

        while current and current.children_ids:
            parent_visits = max(current.visits, 1)
            best_child = None
            best_score = -float("inf")

            for child_id in current.children_ids:
                child = self.nodes[child_id]
                score = child.ucb1_score(
                    parent_visits, self.exploration_weight
                )
                if score > best_score:
                    best_score = score
                    best_child = child

            if best_child:
                current = best_child
            else:
                break

        return current

    def backpropagate(self, node_id: str, value: float) -> None:
        current_id: str | None = node_id
        while current_id and current_id in self.nodes:
            node = self.nodes[current_id]
            node.visits += 1
            node.total_value += value
            self.qd_grid.add_candidate(node)
            current_id = node.parent_id
