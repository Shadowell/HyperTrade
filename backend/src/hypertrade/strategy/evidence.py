from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

STRATEGY_EVIDENCE_SCHEMA_VERSION = "strategy_evidence.v1"


@dataclass(frozen=True, kw_only=True)
class StrategyEvidence:
    """Versioned strategy-memory evidence payload.

    The model is intentionally storage-neutral: Memory keeps exact content
    dedupe/search behavior, while strategy-library readers can parse a stable
    JSON contract before falling back to older text cards.
    """

    strategy_key: str
    experiment_id: str = ""
    research_id: str = ""
    backtest_id: str = ""
    bitpro_result_id: str = ""
    variant_id: str = "n/a"
    variant_count: int = 0
    parameters: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, str] = field(default_factory=dict)
    gate_results: dict[str, bool] = field(default_factory=dict)
    failure_reasons: list[str] = field(default_factory=list)
    source_data: dict[str, str] = field(default_factory=dict)
    next_experiment: str = ""
    boundaries: list[str] = field(default_factory=list)
    passed: bool = False
    schema_version: str = STRATEGY_EVIDENCE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> StrategyEvidence:
        return cls(
            schema_version=_string(payload.get("schema_version")),
            strategy_key=_string(payload.get("strategy_key")),
            experiment_id=_string(payload.get("experiment_id")),
            research_id=_string(payload.get("research_id")),
            backtest_id=_string(payload.get("backtest_id")),
            bitpro_result_id=_string(payload.get("bitpro_result_id")),
            variant_id=_string(payload.get("variant_id"), default="n/a"),
            variant_count=_safe_int(payload.get("variant_count")),
            parameters=_string_mapping(payload.get("parameters")),
            metrics=_string_mapping(payload.get("metrics")),
            gate_results=_bool_mapping(payload.get("gate_results")),
            failure_reasons=_string_list(payload.get("failure_reasons")),
            source_data=_string_mapping(payload.get("source_data")),
            next_experiment=_string(payload.get("next_experiment")),
            boundaries=_string_list(payload.get("boundaries")),
            passed=_bool(payload.get("passed")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategy_key": self.strategy_key,
            "experiment_id": self.experiment_id,
            "research_id": self.research_id,
            "backtest_id": self.backtest_id,
            "bitpro_result_id": self.bitpro_result_id,
            "variant_id": self.variant_id,
            "variant_count": self.variant_count,
            "parameters": self.parameters,
            "metrics": self.metrics,
            "gate_results": self.gate_results,
            "failure_reasons": self.failure_reasons,
            "source_data": self.source_data,
            "next_experiment": self.next_experiment,
            "boundaries": self.boundaries,
            "passed": self.passed,
        }

    def to_memory_content(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return "\n".join(["StrategyEvidence: local strategy experiment evidence", payload])


def parse_strategy_evidence(content: str) -> StrategyEvidence | None:
    payload = _load_json_dict(content)
    if payload is None:
        return None
    if _string(payload.get("schema_version")) != STRATEGY_EVIDENCE_SCHEMA_VERSION:
        return None
    return StrategyEvidence.from_dict(payload)


def _load_json_dict(content: str) -> dict[str, Any] | None:
    text = content.strip()
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
    return None


def _string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    if not text:
        return default
    return text


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, raw_value in value.items():
        clean_key = str(key).strip()
        if not clean_key or raw_value is None:
            continue
        if isinstance(raw_value, (Mapping, list)):
            result[clean_key] = json.dumps(raw_value, ensure_ascii=False, sort_keys=True)
        else:
            result[clean_key] = str(raw_value)
    return result


def _bool_mapping(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, bool] = {}
    for key, raw_value in value.items():
        clean_key = str(key).strip()
        if clean_key:
            result[clean_key] = _bool(raw_value)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes", "pass", "passed"}


def _safe_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
