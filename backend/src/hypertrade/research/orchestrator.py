"""Resumable Sprint 82 worker for bounded BitPro backtest research."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from hypertrade.db import Database, ResearchExperimentEvidence
from hypertrade.memory.service import MemoryService
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import (
    ArtifactReference,
    ExperimentCosts,
    ExperimentExecutionComplete,
    ExperimentManifestV1,
    ExperimentRegister,
    ExperimentVersions,
    ExperimentWindow,
)
from hypertrade.research.robustness import (
    RobustnessValidationService,
    plan_robustness_validation,
)
from hypertrade.research.robustness_schemas import (
    RobustnessPolicyV2,
    ScenarioObservation,
)
from hypertrade.research.schemas import StrategySpecDraft
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.validation import ValidationGate
from hypertrade.strategy.evidence import StrategyEvidence
from hypertrade.tools.registry import ToolRegistry


class BitProResearchAdapter(Protocol):
    def capabilities(self) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...

    def market_klines(
        self, *, symbol: str, timeframe: str, limit: int, exchange: str = "okx"
    ) -> dict[str, Any]: ...

    def strategy_validate_code(
        self, *, script_content: str, idempotency_key: str
    ) -> dict[str, Any]: ...

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def strategy_update(
        self,
        *,
        strategy_id: int,
        name: str | None = None,
        script_content: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str | None = None,
        symbols: list[str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
        wait_for_result: bool = False,
        poll_interval_sec: float = 2.0,
        timeout_sec: float = 90.0,
        maker_fee_bps: float | None = None,
        taker_fee_bps: float | None = None,
        slippage_bps: float | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def backtest_get_result(
        self, *, backtest_id: str | int, sample_limit: int = 20
    ) -> dict[str, Any]: ...


class ResearchRejected(ValueError):
    """A deterministic research-boundary rejection, not an upstream outage."""


class ResearchOrchestrator:
    """Coordinates one durable job without paper/live side effects.

    The boundary is intentional: the worker retains only result references and
    bounded metrics. BitPro remains the source for code, candles, and artifacts.
    """

    def __init__(self, db: Database, *, bitpro_adapter: BitProResearchAdapter) -> None:
        self.db = db
        self.adapter = bitpro_adapter
        self.program = ResearchProgramService(db)
        self.gate = ValidationGate()
        self.tool_calls: list[dict[str, Any]] = []
        self.bitpro_contract_version = "unknown"
        self.data_snapshot_hash = _sha256("unavailable")
        self.preflight_candle_times: list[datetime] = []

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.program.get_job(job_id)
        if job["status"] not in {"queued", "failed"}:
            raise ValueError(f"research job is not runnable from {job['status']}")
        execution_id = ""
        try:
            self.program.transition_job(job_id, target="planning", reason="orchestrator_started")
            mandate = self.program.get_mandate(str(job["mandate_id"]))
            self._advance(job_id, "data_preflight")
            windows = self._preflight_and_windows(job=job, mandate=mandate)
            script_content = _compile_strategy(str(job["strategy_spec"]["strategy_key"]))
            registration = ExperimentLedgerService(self.db).register(
                ExperimentRegister(
                    manifest=_experiment_manifest(
                        job=job,
                        mandate=mandate,
                        windows=windows,
                        script_content=script_content,
                        mcp_contract_version=self.bitpro_contract_version,
                        data_snapshot_hash=self.data_snapshot_hash,
                    ),
                    idempotency_key=f"ledger:{job_id}:attempt:{int(job['attempts']) + 1}",
                    research_job_id=job_id,
                    task_id=str(job.get("source_run_id", "")),
                    force_rerun=job["status"] == "failed",
                    force_reason=(
                        "operator retried failed ResearchJob"
                        if job["status"] == "failed"
                        else ""
                    ),
                ),
                actor="research_orchestrator",
            )
            execution = dict(registration["execution"])
            execution_id = str(execution["id"])
            fingerprint = str(registration["manifest"]["fingerprint"])
            self.program.update_job_external_refs(
                job_id,
                updates={
                    "experiment_ledger": {
                        "fingerprint": fingerprint,
                        "execution_id": execution_id,
                        "attempt": execution["attempt"],
                        "reused": registration["reused"],
                    }
                },
            )
            if registration["reused"]:
                return self._finish_reused_job(
                    job_id,
                    execution=execution,
                    fingerprint=fingerprint,
                )
            ExperimentLedgerService(self.db).start(execution_id)
            _ensure_research_budget(job=job, mandate=mandate, window_count=len(windows))
            self._advance(job_id, "strategy_validation")
            self._validate_strategy(job=job, script_content=script_content)
            strategy_id = self._create_strategy(
                job=job, mandate=mandate, script_content=script_content
            )
            self._advance(job_id, "backtesting")
            evidence = self._run_matrix(
                job=job,
                mandate=mandate,
                strategy_id=strategy_id,
                windows=windows,
            )
            robustness = self._run_robustness(
                job=job,
                mandate=mandate,
                strategy_id=strategy_id,
                execution_id=execution_id,
                fingerprint=fingerprint,
                evidence=evidence,
                existing_backtests=len(evidence) * len(windows),
            )
            self._advance(job_id, "validation")
            passing = [row for row in evidence if row["status"] == "evidence_recorded"]
            if robustness["final_status"] != "validated":
                passing = []
            refs = {
                "bitpro_strategy_id": strategy_id,
                "matrix_candidate_count": len(evidence),
                "passing_candidate_ids": [row["variant_id"] for row in passing],
                "boundary": "backtest_only_no_paper_or_live",
                "robustness_validation_id": robustness["id"],
                "robustness_status": robustness["final_status"],
            }
            self.program.update_job_external_refs(job_id, updates={"sprint_82": refs})
            report = self.program.report(job_id)
            ExperimentLedgerService(self.db).complete(
                execution_id,
                _execution_complete_payload(
                    report=report,
                    strategy_id=strategy_id,
                    contract_version=self.bitpro_contract_version,
                    tool_call_count=len(self.tool_calls),
                    outcome_status="evidence_recorded" if passing else "rejected",
                    robustness=robustness,
                ),
                actor="research_orchestrator",
            )
            if not passing:
                self.program.transition_job(
                    job_id, target="rejected", reason="validation_gates_failed"
                )
            else:
                self.program.transition_job(
                    job_id, target="evidence_recorded", reason="validated_bitpro_evidence_recorded"
                )
            return self.program.report(job_id)
        except ResearchRejected as exc:
            if execution_id:
                ExperimentLedgerService(self.db).fail(
                    execution_id,
                    error={"code": "research_rejected", "message": str(exc)},
                )
            self.program.transition_job(job_id, target="rejected", reason=str(exc))
            return self.program.report(job_id)
        except Exception as exc:  # noqa: BLE001 - persist external failures for safe resume
            if execution_id:
                with suppress(ValueError):
                    ExperimentLedgerService(self.db).fail(
                        execution_id,
                        error={"code": "orchestrator_failed", "type": type(exc).__name__},
                    )
            current = self.program.get_job(job_id)
            if current["status"] not in {"failed", "rejected", "evidence_recorded"}:
                self.program.transition_job(
                    job_id, target="failed", reason=f"upstream_failure:{exc}"
                )
            return self.program.report(job_id)

    def _finish_reused_job(
        self,
        job_id: str,
        *,
        execution: dict[str, Any],
        fingerprint: str,
    ) -> dict[str, Any]:
        status = str(execution["status"])
        self._advance(job_id, "strategy_validation")
        self._advance(job_id, "backtesting")
        self._advance(job_id, "validation")
        if status == "completed":
            self.program.transition_job(
                job_id,
                target="evidence_recorded",
                reason=f"reused_completed_experiment:{fingerprint}",
            )
        else:
            self.program.transition_job(
                job_id,
                target="rejected",
                reason=f"duplicate_experiment_{status}:{fingerprint}",
            )
        return self.program.report(job_id)

    def _advance(self, job_id: str, target: str) -> None:
        self.program.transition_job(job_id, target=target, reason=f"orchestrator:{target}")

    def _preflight_and_windows(
        self, *, job: dict[str, Any], mandate: dict[str, Any]
    ) -> dict[str, dict[str, str]]:
        capabilities = self.adapter.capabilities()
        self.bitpro_contract_version = str(
            capabilities.get("contract_version") or "unknown"
        )
        health = self.adapter.health()
        self._record("bitpro_capabilities", capabilities)
        self._record("bitpro_health", health)
        raw_groups = capabilities.get("tool_groups")
        groups = cast(dict[str, Any], raw_groups) if isinstance(raw_groups, dict) else {}
        raw_available = groups.get("research_backtest_paper_mutation")
        available = (
            {str(tool) for tool in raw_available} if isinstance(raw_available, list) else set()
        )
        required = {"strategy_validate_code", "strategy_create", "backtest_start_job"}
        if not required <= available:
            raise ResearchRejected("bitpro_required_research_tools_unavailable")
        raw_health = health.get("health")
        health_detail = cast(dict[str, Any], raw_health) if isinstance(raw_health, dict) else health
        health_status = str(health_detail.get("status", "")).casefold()
        if health_status not in {"healthy", "ok", "up"}:
            raise RuntimeError("bitpro_health_unavailable")

        spec = job["strategy_spec"]
        symbols = list(spec.get("symbols", []))
        timeframes = list(spec.get("timeframes", []))
        if len(symbols) != 1 or len(timeframes) != 1:
            raise ResearchRejected("sprint_82_requires_one_symbol_and_one_timeframe_per_job")
        validation = mandate["validation"]
        payload = self.adapter.market_klines(
            symbol=str(symbols[0]),
            timeframe=str(timeframes[0]),
            limit=int(validation["min_candle_count"]),
        )
        self._record("market_klines", payload)
        raw_candles = payload.get("candles")
        candles = (
            [cast(dict[str, Any], row) for row in raw_candles if isinstance(row, dict)]
            if isinstance(raw_candles, list)
            else []
        )
        if len(candles) < int(validation["min_candle_count"]):
            raise ResearchRejected("real_data_coverage_inadequate")
        self.data_snapshot_hash = _candle_snapshot_hash(candles)
        self.preflight_candle_times = [_candle_time(row) for row in candles]
        return _chronological_windows(candles, validation=validation)

    def _validate_strategy(self, *, job: dict[str, Any], script_content: str) -> None:
        result = self.adapter.strategy_validate_code(
            script_content=script_content,
            idempotency_key=_idempotency_key(str(job["id"]), "validate"),
        )
        self._record("strategy_validate_code", result)
        raw_validation = result.get("validation")
        validation = (
            cast(dict[str, Any], raw_validation) if isinstance(raw_validation, dict) else {}
        )
        valid = bool(validation.get("valid") or validation.get("passed"))
        valid = valid or str(validation.get("status", "")).casefold() in {"ok", "valid", "passed"}
        if not valid:
            raise ResearchRejected("bitpro_strategy_code_validation_failed")

    def _create_strategy(
        self, *, job: dict[str, Any], mandate: dict[str, Any], script_content: str
    ) -> str:
        spec = job["strategy_spec"]
        symbol = str(spec["symbols"][0])
        timeframe = str(spec["timeframes"][0])
        payload = self.adapter.strategy_create(
            name=_canonical_name(symbol=symbol, timeframe=timeframe, title=str(spec["title"])),
            script_content=script_content,
            description=str(spec["hypothesis"]),
            config={
                "strategy_source": "db_script",
                "script_content_source": "db",
                "market_type": mandate["market_type"],
                "timeframe": timeframe,
                "is_paper_trading": True,
                "research_job_id": job["id"],
            },
            symbols=[symbol],
            idempotency_key=_idempotency_key(str(job["id"]), "strategy-create"),
        )
        self._record("strategy_create", payload)
        raw_strategy = payload.get("strategy")
        strategy = cast(dict[str, Any], raw_strategy) if isinstance(raw_strategy, dict) else {}
        strategy_id = strategy.get("id") or strategy.get("strategy_id")
        if strategy_id is None:
            raise RuntimeError("bitpro_strategy_create_missing_strategy_id")
        return str(strategy_id)

    def _run_matrix(
        self,
        *,
        job: dict[str, Any],
        mandate: dict[str, Any],
        strategy_id: str,
        windows: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        spec = job["strategy_spec"]
        variants = _matrix_variants(
            spec.get("parameter_bounds") if isinstance(spec.get("parameter_bounds"), dict) else {},
            limit=int(mandate["budget"]["max_variants_per_candidate"]),
        )
        projected = len(variants) * len(windows)
        if projected > _per_candidate_backtest_cap(mandate["budget"]):
            raise ResearchRejected("matrix_exceeds_mandate_backtest_budget")

        rows: list[dict[str, Any]] = []
        for variant_id, parameters in variants:
            if variant_id != "baseline":
                update = self.adapter.strategy_update(
                    strategy_id=int(strategy_id),
                    config={
                        "strategy_source": "db_script",
                        "script_content_source": "db",
                        "research_parameters": parameters,
                        "research_job_id": job["id"],
                    },
                    idempotency_key=_idempotency_key(
                        str(job["id"]), f"strategy-update-{variant_id}"
                    ),
                )
                self._record("strategy_update", update)
            results = self._run_variant(
                job=job,
                mandate=mandate,
                strategy_id=strategy_id,
                windows=windows,
                variant_id=variant_id,
            )
            gate = self.gate.evaluate(
                results=results,
                validation=mandate["validation"],
                data_complete=True,
                costs_declared=True,
            )
            row = self._persist_evidence(
                job=job,
                strategy_id=strategy_id,
                variant_id=variant_id,
                parameters=parameters,
                windows=windows,
                results=results,
                gate=gate,
            )
            rows.append(row)
            self._write_library_evidence(job=job, evidence=row)
        return rows

    def _run_variant(
        self,
        *,
        job: dict[str, Any],
        mandate: dict[str, Any],
        strategy_id: str,
        windows: dict[str, dict[str, str]],
        variant_id: str,
    ) -> list[dict[str, Any]]:
        spec = job["strategy_spec"]
        results: list[dict[str, Any]] = []
        for window_name, window in windows.items():
            payload = self.adapter.backtest_start_job(
                strategy_id=int(strategy_id),
                start_date=window["start_date"],
                end_date=window["end_date"],
                symbol=str(spec["symbols"][0]),
                timeframe=str(spec["timeframes"][0]),
                maker_fee_bps=float(mandate["validation"]["fee_bps"]),
                taker_fee_bps=float(mandate["validation"]["fee_bps"]),
                slippage_bps=float(mandate["validation"]["slippage_bps"]),
                wait_for_result=True,
                idempotency_key=_idempotency_key(str(job["id"]), f"{variant_id}-{window_name}"),
            )
            self._record("backtest_start_job", payload)
            detail = _result_from_backtest_payload(payload)
            if not detail:
                raise ResearchRejected(
                    f"completed_bitpro_result_missing:{variant_id}:{window_name}"
                )
            results.append(
                {
                    "window": window_name,
                    "label": f"{variant_id}:{window_name}",
                    "job_id": str((payload.get("job") or {}).get("job_id", "")),
                    "result_id": str(detail.get("id", "")),
                    "metrics": dict(detail.get("metrics") or {}),
                }
            )
        return results

    def _persist_evidence(
        self,
        *,
        job: dict[str, Any],
        strategy_id: str,
        variant_id: str,
        parameters: dict[str, float],
        windows: dict[str, dict[str, str]],
        results: list[dict[str, Any]],
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        with self.db.session() as session:
            evidence = ResearchExperimentEvidence(
                job_id=str(job["id"]),
                mandate_id=str(job["mandate_id"]),
                variant_id=variant_id,
                status="evidence_recorded" if gate["passed"] else "rejected",
                strategy_key=str(job["strategy_spec"]["strategy_key"]),
                bitpro_strategy_id=strategy_id,
                result_refs_json={
                    row["window"]: {"job_id": row["job_id"], "result_id": row["result_id"]}
                    for row in results
                },
                windows_json=windows,
                parameters_json=parameters,
                metrics_json={row["window"]: row["metrics"] for row in results},
                gate_results_json=dict(gate["gate_results"]),
                rejection_reasons_json=list(gate["rejection_reasons"]),
                tool_calls_json=list(self.tool_calls),
            )
            session.add(evidence)
            session.flush()
            return {
                "id": evidence.id,
                "variant_id": evidence.variant_id,
                "status": evidence.status,
                "strategy_key": evidence.strategy_key,
                "bitpro_strategy_id": evidence.bitpro_strategy_id,
                "result_refs": dict(evidence.result_refs_json),
                "windows": dict(evidence.windows_json),
                "parameters": dict(evidence.parameters_json),
                "metrics": dict(evidence.metrics_json),
                "gate_results": dict(evidence.gate_results_json),
                "rejection_reasons": list(evidence.rejection_reasons_json),
            }

    def _write_library_evidence(self, *, job: dict[str, Any], evidence: dict[str, Any]) -> None:
        locked = evidence["metrics"].get("locked_out_of_sample") or {}
        locked_ref = evidence["result_refs"].get("locked_out_of_sample") or {}
        MemoryService(self.db).write(
            content=StrategyEvidence(
                strategy_key=str(evidence["strategy_key"]),
                experiment_id=str(evidence["id"]),
                research_id=str(job["id"]),
                backtest_id=str(locked_ref.get("job_id", "")),
                bitpro_result_id=str(locked_ref.get("result_id", "")),
                variant_id=str(evidence["variant_id"]),
                variant_count=1,
                parameters={key: str(value) for key, value in evidence["parameters"].items()},
                metrics={key: str(value) for key, value in locked.items()},
                gate_results=dict(evidence["gate_results"]),
                failure_reasons=list(evidence["rejection_reasons"]),
                source_data={"source": "bitpro_mcp", "window": "locked_out_of_sample"},
                next_experiment="review passing evidence before any paper approval",
                boundaries=["bitpro_backtest_only", "no_paper_action", "live_disabled"],
                passed=evidence["status"] == "evidence_recorded",
            ).to_memory_content(),
            kind="strategy_knowledge",
            source_run_id=str(job.get("source_run_id", "")),
            source_tool="research.orchestrator",
            tags=["strategy", "strategy_knowledge", "bitpro", str(evidence["strategy_key"])],
        )

    def _run_robustness(
        self,
        *,
        job: dict[str, Any],
        mandate: dict[str, Any],
        strategy_id: str,
        execution_id: str,
        fingerprint: str,
        evidence: list[dict[str, Any]],
        existing_backtests: int,
    ) -> dict[str, Any]:
        validation = dict(mandate["validation"])
        policy = RobustnessPolicyV2(
            locked_oos_bars=int(validation["locked_out_of_sample_bars"]),
            min_trade_count=int(validation["min_trade_count"]),
            max_drawdown_pct=Decimal(str(validation["max_drawdown_pct"])),
        )
        spec = dict(job["strategy_spec"])
        try:
            plan = plan_robustness_validation(
                fingerprint=fingerprint,
                data_snapshot_hash=self.data_snapshot_hash,
                candle_times=self.preflight_candle_times,
                parameter_bounds=dict(spec.get("parameter_bounds", {})),
                maker_fee_bps=Decimal(str(validation["fee_bps"])),
                taker_fee_bps=Decimal(str(validation["fee_bps"])),
                slippage_bps=Decimal(str(validation["slippage_bps"])),
                policy=policy,
                max_new_backtests=(
                    _per_candidate_backtest_cap(mandate["budget"]) - existing_backtests
                ),
            )
        except ValueError as exc:
            raise ResearchRejected(f"robustness_planning_rejected:{exc}") from exc
        evidence_by_variant = {str(row["variant_id"]): row for row in evidence}
        observations: list[ScenarioObservation] = []
        baseline = evidence_by_variant.get("baseline", {})
        for scenario in plan.scenarios:
            if scenario.source == "reuse":
                variant = (
                    "baseline"
                    if scenario.kind == "locked_oos"
                    else f"adjacent_{next(iter(scenario.parameters), '')}"
                )
                source = evidence_by_variant.get(variant, baseline if variant == "baseline" else {})
                observations.append(
                    _scenario_observation_from_evidence(scenario.scenario_id, source)
                )
        if any(item.source == "execute" for item in plan.scenarios):
            reset = self.adapter.strategy_update(
                strategy_id=int(strategy_id),
                config={
                    "strategy_source": "db_script",
                    "script_content_source": "db",
                    "research_parameters": {},
                    "research_job_id": job["id"],
                },
                idempotency_key=_idempotency_key(str(job["id"]), "robustness-reset"),
            )
            self._record("strategy_update", reset)
        for scenario in plan.scenarios:
            if scenario.source != "execute":
                continue
            payload = self.adapter.backtest_start_job(
                strategy_id=int(strategy_id),
                start_date=scenario.window.start.date().isoformat(),
                end_date=scenario.window.end.date().isoformat(),
                symbol=str(spec["symbols"][0]),
                timeframe=str(spec["timeframes"][0]),
                maker_fee_bps=float(scenario.maker_fee_bps),
                taker_fee_bps=float(scenario.taker_fee_bps),
                slippage_bps=float(scenario.slippage_bps),
                wait_for_result=True,
                idempotency_key=_idempotency_key(
                    str(job["id"]), f"robustness-{scenario.scenario_id}"
                ),
            )
            self._record("backtest_start_job", payload)
            detail = _result_from_backtest_payload(payload)
            if not detail:
                observations.append(
                    ScenarioObservation(
                        scenario_id=scenario.scenario_id,
                        status="unknown",
                        error_code="completed_bitpro_result_missing",
                    )
                )
                continue
            observations.append(
                ScenarioObservation(
                    scenario_id=scenario.scenario_id,
                    status="completed",
                    result_ref={
                        "job_id": str((payload.get("job") or {}).get("job_id", "")),
                        "result_id": str(detail.get("id", "")),
                    },
                    metrics=_decimal_metrics(dict(detail.get("metrics") or {})),
                )
            )
        return RobustnessValidationService(self.db).record(
            execution_id=execution_id,
            plan=plan,
            policy=policy,
            observations=observations,
            actor="research_orchestrator",
        )

    def _record(self, tool: str, payload: dict[str, Any]) -> None:
        raw_calls = payload.get("tool_calls")
        calls = raw_calls if isinstance(raw_calls, list) else []
        self.tool_calls.extend(
            {"stage_tool": tool, **dict(call)} for call in calls if isinstance(call, dict)
        )


def _experiment_manifest(
    *,
    job: dict[str, Any],
    mandate: dict[str, Any],
    windows: dict[str, dict[str, str]],
    script_content: str,
    mcp_contract_version: str,
    data_snapshot_hash: str,
) -> ExperimentManifestV1:
    spec = StrategySpecDraft.model_validate(job["strategy_spec"])
    window_models = [
        ExperimentWindow(
            name=name,
            start=datetime.fromisoformat(value["start_date"]).replace(tzinfo=UTC),
            end=(
                datetime.fromisoformat(value["end_date"]).replace(tzinfo=UTC)
                + _one_day()
            ),
        )
        for name, value in sorted(windows.items())
    ]
    validation = dict(mandate["validation"])
    policy_payload = {
        "budget": mandate["budget"],
        "validation": validation,
        "paper_promotion_mode": mandate["paper_promotion_mode"],
        "live_mode": mandate["live_mode"],
    }
    return ExperimentManifestV1(
        strategy_spec=spec,
        strategy_code_sha256=_sha256(script_content),
        strategy_code_ref=f"hypertrade:compiled:{spec.strategy_key}",
        parameters={},
        exchange="OKX",
        market_type=str(mandate["market_type"]),
        windows=window_models,
        costs=ExperimentCosts(
            maker_fee_bps=Decimal(str(validation["fee_bps"])),
            taker_fee_bps=Decimal(str(validation["fee_bps"])),
            slippage_bps=Decimal(str(validation["slippage_bps"])),
            funding_mode="included" if validation["include_funding"] else "excluded",
        ),
        data_snapshot_hash=data_snapshot_hash,
        versions=ExperimentVersions(
            provider="research_orchestrator",
            model="deterministic_bitpro_matrix_v1",
            prompt_hash=_sha256(" ".join(str(job["prompt"]).split())),
            tool_registry_hash=_tool_registry_hash(),
            policy_hash=_sha256(
                json.dumps(policy_payload, separators=(",", ":"), sort_keys=True)
            ),
            mcp_contract_version=mcp_contract_version,
            git_commit_sha=os.getenv("HYPERTRADE_GIT_SHA", "unknown0")[:64],
        ),
    )


def _execution_complete_payload(
    *,
    report: dict[str, Any],
    strategy_id: str,
    contract_version: str,
    tool_call_count: int,
    outcome_status: str,
    robustness: dict[str, Any],
) -> ExperimentExecutionComplete:
    evidence = [dict(item) for item in report.get("evidence", [])]
    artifacts: list[ArtifactReference] = []
    metrics: dict[str, Decimal] = {}
    for item in evidence:
        variant = str(item.get("variant_id", "variant"))
        for window, ref in sorted(dict(item.get("result_refs", {})).items()):
            bounded_ref = {
                "job_id": str(dict(ref).get("job_id", "")),
                "result_id": str(dict(ref).get("result_id", "")),
            }
            artifacts.append(
                ArtifactReference(
                    artifact_id=f"{variant}:{window}",
                    artifact_ref=(
                        f"bitpro:backtest:{bounded_ref['job_id']}:{bounded_ref['result_id']}"
                    ),
                    content_hash=_sha256(
                        json.dumps(bounded_ref, separators=(",", ":"), sort_keys=True)
                    ),
                    contract_version=contract_version,
                )
            )
        locked = dict(item.get("metrics", {})).get("locked_out_of_sample", {})
        for key, value in sorted(dict(locked).items()):
            try:
                metrics[f"{variant}.locked.{key}"] = Decimal(str(value))
            except InvalidOperation:
                continue
    for scenario in robustness.get("scenarios", []):
        ref = dict(scenario.get("result_ref", {}))
        if not ref:
            continue
        bounded_ref = {
            "job_id": str(ref.get("job_id", "")),
            "result_id": str(ref.get("result_id", "")),
        }
        artifacts.append(
            ArtifactReference(
                artifact_id=f"robustness:{scenario.get('scenario_id', 'scenario')}",
                artifact_ref=(
                    f"bitpro:backtest:{bounded_ref['job_id']}:{bounded_ref['result_id']}"
                ),
                content_hash=_sha256(
                    json.dumps(bounded_ref, separators=(",", ":"), sort_keys=True)
                ),
                contract_version=contract_version,
            )
        )
    return ExperimentExecutionComplete(
        external_refs={
            "bitpro_strategy_id": strategy_id,
            "research_job_id": str(report["job"]["id"]),
            "outcome_status": outcome_status,
            "robustness_validation_id": str(robustness["id"]),
            "robustness_status": str(robustness["final_status"]),
        },
        metrics=metrics,
        artifacts=artifacts,
        usage={
            "backtests": len(evidence) * 3
            + int(dict(robustness.get("plan", {})).get("projected_new_backtests", 0)),
            "tool_calls": tool_call_count,
        },
        evidence_ids=[str(item["id"]) for item in evidence],
        evidence_kind="legacy_experiment",
    )


def _tool_registry_hash() -> str:
    payload = [
        {
            "name": tool.name,
            "category": tool.category,
            "policy": tool.policy.to_dict(),
        }
        for tool in sorted(ToolRegistry.default().list_tools(), key=lambda item: item.name)
    ]
    return _sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _one_day() -> timedelta:
    return timedelta(days=1)


def _candle_snapshot_hash(candles: list[dict[str, Any]]) -> str:
    """Hash bounded candle identities, never raw market values."""
    identities = sorted(_candle_time(row).isoformat() for row in candles)
    return _sha256(json.dumps(identities, separators=(",", ":")))


def _scenario_observation_from_evidence(
    scenario_id: str, evidence: dict[str, Any]
) -> ScenarioObservation:
    metrics = dict(evidence.get("metrics", {})).get("locked_out_of_sample", {})
    result_ref = dict(evidence.get("result_refs", {})).get("locked_out_of_sample", {})
    if not isinstance(metrics, dict) or not isinstance(result_ref, dict) or not result_ref:
        return ScenarioObservation(
            scenario_id=scenario_id,
            status="unknown",
            error_code="reused_locked_oos_evidence_missing",
        )
    return ScenarioObservation(
        scenario_id=scenario_id,
        status="completed",
        result_ref={
            "job_id": str(result_ref.get("job_id", "")),
            "result_id": str(result_ref.get("result_id", "")),
        },
        metrics=_decimal_metrics(metrics),
    )


def _decimal_metrics(metrics: dict[str, Any]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for key, value in metrics.items():
        parsed = _decimal(value)
        if parsed is not None and parsed.is_finite():
            result[str(key)] = parsed
    return result


def _per_candidate_backtest_cap(budget: dict[str, Any]) -> int:
    candidates = max(1, int(budget["max_candidates_per_day"]))
    baseline = int(budget["max_variants_per_candidate"]) * 3
    return max(baseline, int(budget["max_total_backtests_per_day"]) // candidates)


def _ensure_research_budget(
    *, job: dict[str, Any], mandate: dict[str, Any], window_count: int
) -> None:
    bounds = job["strategy_spec"].get("parameter_bounds", {})
    variants = _matrix_variants(
        bounds if isinstance(bounds, dict) else {},
        limit=int(mandate["budget"]["max_variants_per_candidate"]),
    )
    projected = len(variants) * window_count + 4
    if projected > _per_candidate_backtest_cap(mandate["budget"]):
        raise ResearchRejected("robustness_plan_exceeds_per_candidate_backtest_budget")


def _chronological_windows(
    candles: list[dict[str, Any]], *, validation: dict[str, Any]
) -> dict[str, dict[str, str]]:
    ordered = sorted((_candle_time(row) for row in candles), key=lambda value: value)
    if len(ordered) < int(validation["min_candle_count"]):
        raise ResearchRejected("real_data_coverage_inadequate")
    ordered = ordered[-int(validation["min_candle_count"]) :]
    sizes = [
        ("in_sample", int(validation["in_sample_bars"])),
        ("validation", int(validation["validation_bars"])),
        ("locked_out_of_sample", int(validation["locked_out_of_sample_bars"])),
    ]
    cursor = 0
    windows: dict[str, dict[str, str]] = {}
    for name, size in sizes:
        segment = ordered[cursor : cursor + size]
        if len(segment) != size:
            raise ResearchRejected("chronological_window_unavailable")
        windows[name] = {
            "start_date": segment[0].date().isoformat(),
            "end_date": segment[-1].date().isoformat(),
        }
        cursor += size
    return windows


def _matrix_variants(bounds: dict[str, Any], *, limit: int) -> list[tuple[str, dict[str, float]]]:
    variants: list[tuple[str, dict[str, float]]] = [("baseline", {})]
    for key in sorted(bounds):
        if len(variants) >= limit:
            break
        bound = bounds[key] if isinstance(bounds[key], dict) else {}
        low, high = _decimal(bound.get("min")), _decimal(bound.get("max"))
        if low is None or high is None or high < low:
            continue
        variants.append((f"adjacent_{key}", {key: float((low + high) / Decimal("2"))}))
    return variants[:limit]


def _compile_strategy(strategy_key: str) -> str:
    class_name = "Research" + "".join(part.capitalize() for part in strategy_key.split("_"))[:80]
    return "\n".join(
        [
            "from app.core.execution.base_strategy import BaseStrategy",
            "",
            f"class {class_name}(BaseStrategy):",
            '    """Bounded dynamic DB moving-average research candidate."""',
            "",
            "    def __init__(self, config=None):",
            "        super().__init__(config or {})",
            '        params = self.config.get("research_parameters", {})',
            '        self.fast_window = max(2, int(params.get("fast_window", 8)))',
            (
                "        self.slow_window = max("
                'self.fast_window + 1, int(params.get("slow_window", 32)))'
            ),
            (
                "        self.trade_notional_usdt = float("
                'self.config.get("trade_notional_usdt", 1000.0))'
            ),
            "",
            "    async def on_bar(self, bar):",
            '        symbol = bar.symbol or self.config.get("symbol")',
            "        close = float(bar.close or 0)",
            "        if not symbol or close <= 0:",
            "            return None",
            "        history = self.get_recent_bars(symbol, limit=self.slow_window)",
            "        if len(history) < self.slow_window:",
            "            return None",
            "        closes = [float(item.close or 0) for item in history]",
            "        fast_ma = sum(closes[-self.fast_window:]) / self.fast_window",
            "        slow_ma = sum(closes[-self.slow_window:]) / self.slow_window",
            "        position = self.get_position(symbol)",
            "        quantity = float(position.quantity or 0) if position else 0.0",
            "        if fast_ma > slow_ma and quantity <= 0:",
            "            return self.buy(symbol=symbol, amount=self.trade_notional_usdt / close)",
            "        if fast_ma < slow_ma and quantity > 0:",
            "            return self.sell(symbol=symbol, amount=quantity)",
            "        return None",
            "",
        ]
    )


def _canonical_name(*, symbol: str, timeframe: str, title: str) -> str:
    asset = symbol.split("/")[0].split("-")[0].upper()
    return f"[合约][{timeframe.upper()}][CTA] {asset} · {title[:48]} · 10000U"


def _idempotency_key(job_id: str, suffix: str) -> str:
    return f"{job_id}:{suffix}"[:128]


def _result_from_backtest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("backtest_result") or payload.get("result")
    return dict(result) if isinstance(result, dict) else {}


def _candle_time(row: dict[str, Any]) -> datetime:
    raw = row.get("timestamp") or row.get("ts") or row.get("time")
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw) / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    text = str(raw or "").replace("Z", "+00:00")
    if not text:
        raise ResearchRejected("real_data_timestamp_missing")
    parsed = datetime.fromisoformat(text)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
