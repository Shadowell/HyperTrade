"""Durable, operator-governed strategy research program services."""

from hypertrade.research.a_share_rules import (
    AShareMarketRules,
    ASharePromptContext,
    AShareRuleValidator,
    AShareValidationReport,
)
from hypertrade.research.co_steer import (
    ASTGatekeeper,
    ASTValidationResult,
    BaseEvolutionStrategy,
    LocalSelfHealController,
    SelfHealResult,
)
from hypertrade.research.hypothesis_tree import (
    DuplicateHypothesisError,
    HypothesisTreeService,
    MaxTreeDepthExceededError,
)
from hypertrade.research.orchestrator import ResearchOrchestrator
from hypertrade.research.paper_promotion import PaperPromotionService
from hypertrade.research.quantlab_transpiler import (
    QuantLabStrategyTranspiler,
    TranspiledQuantLabStrategy,
)
from hypertrade.research.service import ResearchProgramService

__all__ = [
    "AShareMarketRules",
    "ASharePromptContext",
    "AShareRuleValidator",
    "AShareValidationReport",
    "ASTGatekeeper",
    "ASTValidationResult",
    "BaseEvolutionStrategy",
    "DuplicateHypothesisError",
    "HypothesisTreeService",
    "LocalSelfHealController",
    "MaxTreeDepthExceededError",
    "PaperPromotionService",
    "QuantLabStrategyTranspiler",
    "ResearchOrchestrator",
    "ResearchProgramService",
    "SelfHealResult",
    "TranspiledQuantLabStrategy",
]
