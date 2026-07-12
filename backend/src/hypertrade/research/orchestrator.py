"""Resumable Sprint 82 worker for bounded BitPro backtest research."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from hypertrade.db import Database, ResearchExperimentEvidence
from hypertrade.memory.service import MemoryService
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.validation import ValidationGate
from hypertrade.strategy.evidence import StrategyEvidence


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

    def run(self, job_id: str) -> dict[str, Any]:
        job = self.program.get_job(job_id)
        if job["status"] not in {"queued", "failed"}:
            raise ValueError(f"research job is not runnable from {job['status']}")
        try:
            self.program.transition_job(job_id, target="planning", reason="orchestrator_started")
            mandate = self.program.get_mandate(str(job["mandate_id"]))
            self._advance(job_id, "data_preflight")
            windows = self._preflight_and_windows(job=job, mandate=mandate)
            self._advance(job_id, "strategy_validation")
            script_content = _compile_strategy(str(job["strategy_spec"]["strategy_key"]))
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
            self._advance(job_id, "validation")
            passing = [row for row in evidence if row["status"] == "evidence_recorded"]
            refs = {
                "bitpro_strategy_id": strategy_id,
                "matrix_candidate_count": len(evidence),
                "passing_candidate_ids": [row["variant_id"] for row in passing],
                "boundary": "backtest_only_no_paper_or_live",
            }
            self.program.update_job_external_refs(job_id, updates={"sprint_82": refs})
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
            self.program.transition_job(job_id, target="rejected", reason=str(exc))
            return self.program.report(job_id)
        except Exception as exc:  # noqa: BLE001 - persist external failures for safe resume
            self.program.transition_job(job_id, target="failed", reason=f"upstream_failure:{exc}")
            return self.program.report(job_id)

    def _advance(self, job_id: str, target: str) -> None:
        self.program.transition_job(job_id, target=target, reason=f"orchestrator:{target}")

    def _preflight_and_windows(
        self, *, job: dict[str, Any], mandate: dict[str, Any]
    ) -> dict[str, dict[str, str]]:
        capabilities = self.adapter.capabilities()
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
        if projected > int(mandate["budget"]["max_total_backtests_per_day"]):
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

    def _record(self, tool: str, payload: dict[str, Any]) -> None:
        raw_calls = payload.get("tool_calls")
        calls = raw_calls if isinstance(raw_calls, list) else []
        self.tool_calls.extend(
            {"stage_tool": tool, **dict(call)} for call in calls if isinstance(call, dict)
        )


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
            "from app.strategies.base_strategy import BaseStrategy",
            "",
            f"class {class_name}(BaseStrategy):",
            '    """Bounded dynamic DB research candidate."""',
            "    def on_bar(self, context):",
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
