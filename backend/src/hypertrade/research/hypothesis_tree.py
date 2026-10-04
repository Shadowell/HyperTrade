"""Hypothesis Evolution Tree (HET) Service (RD-Agent integration).

Implements:
1. Hypothesis DAG branching and lineage tracking.
2. Semantic deduplication check preventing repetitive hypothesis generation.
3. Automatic branch pruning based on benchmark-relative PnL and Sharpe deterioration.
4. Active branch querying and best-candidate promotion.
"""

from __future__ import annotations

from decimal import Decimal

from hypertrade.memory.layered_service import (
    HypothesisNodeV1,
    HypothesisStatus,
    LayeredMemoryService,
    MutationType,
    cosine_similarity,
    deterministic_embedding,
)


class DuplicateHypothesisError(ValueError):
    """Raised when a proposed hypothesis is semantically redundant with an existing node."""


class MaxTreeDepthExceededError(ValueError):
    """Raised when tree branch depth exceeds maximum allowed limit."""


class HypothesisTreeService:
    """Manages RD-Agent hypothesis evolution trees, deduplication, and pruning."""

    def __init__(self, memory_service: LayeredMemoryService) -> None:
        self.memory_service = memory_service

    def create_tree(
        self,
        *,
        tree_id: str,
        claim: str,
        rationale: str = "",
        target_regimes: list[str] | None = None,
    ) -> HypothesisNodeV1:
        """Create the root hypothesis node for a research mission tree."""
        root = HypothesisNodeV1(
            tree_id=tree_id,
            parent_id=None,
            depth=0,
            claim=claim,
            rationale=rationale,
            target_regimes=target_regimes or [],
            mutation_type=MutationType.INIT,
            status=HypothesisStatus.PROPOSED,
        )
        node_id = self.memory_service.record_hypothesis(root)
        root.id = node_id
        return root

    def propose_branch(
        self,
        *,
        tree_id: str,
        parent_id: str,
        mutation_type: MutationType,
        claim: str,
        rationale: str = "",
        target_regimes: list[str] | None = None,
        max_depth: int = 5,
        deduplication_threshold: float = 0.88,
    ) -> HypothesisNodeV1:
        """Propose a mutated child hypothesis with depth and semantic deduplication checks."""
        parent = self.memory_service.get_hypothesis(parent_id)
        if parent is None:
            raise ValueError(f"Parent hypothesis node not found: {parent_id}")

        if parent.depth >= max_depth:
            raise MaxTreeDepthExceededError(
                f"Parent depth {parent.depth} already at or exceeds max depth {max_depth}"
            )

        # 1. Semantic Deduplication Check
        existing_nodes = self.memory_service.list_hypotheses_for_tree(tree_id)
        new_emb = deterministic_embedding(claim)
        for node in existing_nodes:
            existing_emb = deterministic_embedding(node.claim)
            sim = cosine_similarity(new_emb, existing_emb)
            if sim >= deduplication_threshold:
                raise DuplicateHypothesisError(
                    f"Redundant hypothesis (sim={sim:.2f}) with node {node.id}: '{node.claim}'"
                )

        child = HypothesisNodeV1(
            tree_id=tree_id,
            parent_id=parent_id,
            depth=parent.depth + 1,
            claim=claim,
            rationale=rationale,
            target_regimes=target_regimes or parent.target_regimes,
            mutation_type=mutation_type,
            status=HypothesisStatus.PROPOSED,
        )
        child_id = self.memory_service.record_hypothesis(child)
        child.id = child_id
        return child

    def evaluate_and_prune_node(
        self,
        *,
        node_id: str,
        relative_pnl: Decimal,
        sharpe: Decimal,
        strategy_digest: str | None = None,
        experiment_id: str | None = None,
    ) -> HypothesisNodeV1:
        """Evaluate backtest results and prune branch if underperforming relative to parent."""
        node = self.memory_service.get_hypothesis(node_id)
        if node is None:
            raise ValueError(f"Hypothesis node not found: {node_id}")

        parent = self.memory_service.get_hypothesis(node.parent_id) if node.parent_id else None

        # Check pruning: child is worse than parent on both relative PnL and Sharpe
        is_pruned = False
        prune_reason: str | None = None

        if parent is not None:
            parent_pnl = parent.benchmark_relative_pnl
            parent_sharpe = parent.sharpe_ratio
            if (
                parent_pnl is not None
                and relative_pnl < parent_pnl
                and parent_sharpe is not None
                and sharpe < parent_sharpe
            ):
                is_pruned = True
                prune_reason = (
                    f"Deteriorated relative PnL ({relative_pnl} < {parent_pnl}) "
                    f"and Sharpe ({sharpe} < {parent_sharpe}) vs parent"
                )

        if is_pruned:
            new_status = HypothesisStatus.PRUNED
        elif relative_pnl > Decimal("0.05"):
            new_status = HypothesisStatus.PROMOTED
        else:
            new_status = HypothesisStatus.TESTED

        self.memory_service.update_hypothesis_status(
            node_id,
            status=new_status,
            prune_reason=prune_reason,
            relative_pnl=relative_pnl,
            sharpe=sharpe,
            strategy_digest=strategy_digest,
            experiment_id=experiment_id,
        )

        updated = self.memory_service.get_hypothesis(node_id)
        assert updated is not None
        return updated

    def get_active_leaves(self, tree_id: str) -> list[HypothesisNodeV1]:
        """Return non-pruned leaf nodes eligible for further research/mutation."""
        nodes = self.memory_service.list_hypotheses_for_tree(tree_id)
        all_ids = {n.id for n in nodes if n.id}
        parent_ids = {n.parent_id for n in nodes if n.parent_id}

        # Leaf nodes are those that are not parents of any other node and not pruned
        leaves = [
            n for n in nodes
            if n.id in all_ids
            and n.id not in parent_ids
            and n.status != HypothesisStatus.PRUNED
        ]
        return leaves

    def get_best_candidate(self, tree_id: str) -> HypothesisNodeV1 | None:
        """Return the best tested/promoted non-pruned candidate by benchmark-relative PnL."""
        nodes = self.memory_service.list_hypotheses_for_tree(tree_id)
        valid = [
            n for n in nodes
            if n.status in {HypothesisStatus.TESTED, HypothesisStatus.PROMOTED}
            and n.benchmark_relative_pnl is not None
        ]
        if not valid:
            return None
        valid.sort(key=lambda x: x.benchmark_relative_pnl or Decimal("-999"), reverse=True)
        return valid[0]
