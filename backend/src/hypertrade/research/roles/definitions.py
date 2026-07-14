"""Immutable role catalog and prompt hashes for Research Graph V1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RoleBudget:
    max_model_calls: int = 3
    max_tool_calls: int = 4
    max_tokens: int = 8_000
    timeout_seconds: int = 90


@dataclass(frozen=True)
class RoleDefinition:
    key: str
    version: str
    prompt_file: str
    allowed_tools: tuple[str, ...]
    required: bool
    budget: RoleBudget
    description: str

    @property
    def prompt(self) -> str:
        return (Path(__file__).parent / "prompts" / self.prompt_file).read_text(encoding="utf-8")

    @property
    def prompt_hash(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    def projection(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "version": self.version,
            "prompt_hash": self.prompt_hash,
            "allowed_tools": list(self.allowed_tools),
            "required": self.required,
            "budget": {
                "max_model_calls": self.budget.max_model_calls,
                "max_tool_calls": self.budget.max_tool_calls,
                "max_tokens": self.budget.max_tokens,
                "timeout_seconds": self.budget.timeout_seconds,
            },
            "description": self.description,
        }


_READ_EVIDENCE = ("research.evidence_read",)

ROLE_CATALOG: dict[str, RoleDefinition] = {
    "preflight": RoleDefinition(
        "preflight",
        "preflight.v1",
        "preflight_v1.md",
        ("research.mandate_read", "bitpro.capabilities", "bitpro.health"),
        True,
        RoleBudget(max_tool_calls=3, max_tokens=4_000),
        "Verify mandate, runtime capabilities, and source health without conclusions.",
    ),
    "data_quality": RoleDefinition(
        "data_quality",
        "data_quality.v1",
        "data_quality_v1.md",
        ("research.mandate_read", "market.tickers", "bitpro.market_klines"),
        True,
        RoleBudget(max_tool_calls=3, max_tokens=6_000),
        "Assess source freshness, coverage, and gaps before analysis.",
    ),
    "market_regime": RoleDefinition(
        "market_regime",
        "market_regime.v1",
        "market_regime_v1.md",
        ("global_market.snapshot", "market.tickers", "bitpro.market_klines"),
        True,
        RoleBudget(max_tool_calls=3),
        "Classify bounded market regimes from source-backed observations.",
    ),
    "technical_structure": RoleDefinition(
        "technical_structure",
        "technical_structure.v1",
        "technical_structure_v1.md",
        ("bitpro.market_klines", "market.tickers", "strategy.library_search"),
        True,
        RoleBudget(max_tool_calls=3),
        "Describe technical structure without treating one indicator as a conclusion.",
    ),
    "derivatives_flow": RoleDefinition(
        "derivatives_flow",
        "derivatives_flow.v1",
        "derivatives_flow_v1.md",
        ("market.intelligence", "bitpro.market_klines"),
        False,
        RoleBudget(max_tool_calls=2, max_tokens=6_000),
        "Assess derivatives flow or emit an explicit data gap.",
    ),
    "event_context": RoleDefinition(
        "event_context",
        "event_context.v1",
        "event_context_v1.md",
        ("rag.search",),
        False,
        RoleBudget(max_tool_calls=2, max_tokens=6_000),
        "Capture event context without converting news directly into a signal.",
    ),
    "evidence_synthesis": RoleDefinition(
        "evidence_synthesis",
        "evidence_synthesis.v1",
        "evidence_synthesis_v1.md",
        _READ_EVIDENCE,
        True,
        RoleBudget(max_tool_calls=1),
        "Synthesize support, conflicts, freshness, and gaps from Task evidence only.",
    ),
    "bull_case": RoleDefinition(
        "bull_case",
        "bull_case.v1",
        "bull_case_v1.md",
        _READ_EVIDENCE,
        True,
        RoleBudget(max_tool_calls=1, max_tokens=6_000),
        "Build the strongest source-bound upside case and its invalidation.",
    ),
    "bear_case": RoleDefinition(
        "bear_case",
        "bear_case.v1",
        "bear_case_v1.md",
        _READ_EVIDENCE,
        True,
        RoleBudget(max_tool_calls=1, max_tokens=6_000),
        "Challenge the upside case and surface adverse evidence.",
    ),
    "strategy_engineer": RoleDefinition(
        "strategy_engineer",
        "strategy_engineer.v1",
        "strategy_engineer_v1.md",
        ("research.evidence_read", "research.strategy_spec_draft"),
        True,
        RoleBudget(max_tool_calls=2),
        "Create a bounded StrategySpec draft; never write directly to BitPro.",
    ),
    "bitpro_validation": RoleDefinition(
        "bitpro_validation",
        "bitpro_validation.v1",
        "bitpro_validation_v1.md",
        ("research.job_report", "bitpro.backtest_get_job", "bitpro.backtest_get_result"),
        True,
        RoleBudget(max_tool_calls=3, max_tokens=6_000, timeout_seconds=120),
        "Read trusted BitPro validation results produced by the existing orchestrator.",
    ),
    "validation_reviewer": RoleDefinition(
        "validation_reviewer",
        "validation_reviewer.v1",
        "validation_reviewer_v1.md",
        ("research.evidence_read", "research.job_report"),
        True,
        RoleBudget(max_tool_calls=2),
        "Review deterministic validation evidence without changing gate metrics.",
    ),
    "risk_committee": RoleDefinition(
        "risk_committee",
        "risk_committee.v1",
        "risk_committee_v1.md",
        ("research.evidence_read", "world_model.snapshot"),
        True,
        RoleBudget(max_tool_calls=2),
        "Issue a research candidate decision only; no allocation or trading mutation.",
    ),
}

RESEARCH_GRAPH_EDGES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("__start__",), "preflight"),
    (("preflight",), "data_quality"),
    (("data_quality",), "market_regime"),
    (("data_quality",), "technical_structure"),
    (("data_quality",), "derivatives_flow"),
    (("data_quality",), "event_context"),
    (
        ("market_regime", "technical_structure", "derivatives_flow", "event_context"),
        "evidence_synthesis",
    ),
    (("evidence_synthesis",), "bull_case"),
    (("evidence_synthesis",), "bear_case"),
    (("bull_case", "bear_case"), "strategy_engineer"),
    (("strategy_engineer",), "bitpro_validation"),
    (("bitpro_validation",), "validation_reviewer"),
    (("validation_reviewer",), "risk_committee"),
    (("risk_committee",), "__end__"),
)


def role_catalog_hash() -> str:
    serialized = json.dumps(
        [ROLE_CATALOG[key].projection() for key in sorted(ROLE_CATALOG)],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
