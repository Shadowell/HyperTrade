"""Production variant-generation pipeline, bootstrap preset, and review capital tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade import worker
from hypertrade.arc.auth import hash_service_token
from hypertrade.arc.auto_review import auto_review_once, evaluate_auto_review
from hypertrade.arc.avo import run_pending_avo_once
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import (
    EVOLUTION_PRESETS,
    EvolutionConfig,
    EvolutionService,
    effective_validation_criteria,
)
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.paper_review import request_paper_review
from hypertrade.arc.store import configure_store, get_controller, reset_store
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from test_arc_selection_bias import stats


@pytest.fixture
def evo_db() -> Iterator[Database]:
    reset_store()
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    yield db
    reset_store()


def _frozen_cost_config(**extra: Any) -> dict[str, Any]:
    values = {
        "taker_fee_bps": 5.0,
        "maker_fee_bps": 2.0,
        "slippage_bps": 1.0,
        "funding_mode": "not_modeled",
    }
    policy: dict[str, Any] = {
        "version": "research_costs.v1",
        "source": "bitpro_backtest_cost_resolver",
        "exchange": "okx",
        "market_type": "swap",
        "values": values,
    }
    policy["hash"] = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return {
        **values,
        **extra,
        "_freeze_research_costs": True,
        "_research_cost_policy": policy,
    }


def test_evolution_config_defaults_stay_unchanged() -> None:
    defaults = EvolutionConfig()
    assert defaults.enabled is True
    assert defaults.launch_enabled is False
    assert defaults.launch_days == 7
    assert defaults.research_provider == "codex"
    assert defaults.exploration_provider == "research"
    assert defaults.exploration_cooldown_hours == 24
    assert defaults.paper_admission == "strict"
    assert defaults.paper_review_mode == "human"
    assert defaults.paper_capital == Decimal("100")
    assert defaults.max_research_per_day == 4
    assert defaults.max_candidates == 3


def test_production_3slot_preset_and_bootstrap_are_idempotent_and_safe(evo_db: Database) -> None:
    service = EvolutionService(evo_db)

    # Unknown preset fails closed.
    with pytest.raises(ValueError, match="unknown evolution preset"):
        service.ensure_bootstrap_preset("nonexistent_preset")
    with pytest.raises(ValueError, match="unknown evolution preset"):
        service.apply_preset("nonexistent_preset", actor="ops")

    # Cold start DB with no global row applies production_3slot once.
    applied = service.ensure_bootstrap_preset("production_3slot")
    assert applied is not None
    assert applied["revision"] == 1
    for key, value in EVOLUTION_PRESETS["production_3slot"].items():
        assert applied["config"][key] == value
    # Unspecified fields retain EvolutionConfig defaults.
    assert applied["config"]["paper_capital"] == "100"
    assert applied["config"]["research_provider"] == "codex"

    # Second call is a strict no-op and never bumps revision or overwrites edits.
    assert service.ensure_bootstrap_preset("production_3slot") is None
    assert service.status()["revision"] == 1

    # On a fresh DB where an operator already persisted a config, bootstrap never overwrites it.
    reset_store()
    operator_db = Database("sqlite:///:memory:")
    operator_db.create_all()
    configure_store(operator_db)
    op_service = EvolutionService(operator_db)
    op_service.configure(
        EvolutionConfig(
            enabled=False,
            launch_enabled=False,
            paper_capital=Decimal("250"),
            strategy_ids=[107],
        ),
        revision=0,
        actor="operator",
    )
    assert op_service.ensure_bootstrap_preset("production_3slot") is None
    current = op_service.status()
    assert current["revision"] == 1
    assert current["config"]["enabled"] is False
    assert current["config"]["launch_enabled"] is False
    assert current["config"]["paper_capital"] == "250"

    # Explicit apply_preset merges onto current config while preserving unrelated operator fields.
    merged = op_service.apply_preset("production_3slot", actor="operator")
    assert merged["revision"] == 2
    assert merged["config"]["enabled"] is True
    assert merged["config"]["launch_enabled"] is True
    assert merged["config"]["paper_capital"] == "250"
    assert merged["config"]["strategy_ids"] == [107]


def test_evolution_preset_http_endpoint_enforces_scope_and_validation() -> None:
    reset_store()
    db = Database("sqlite:///:memory:")
    db.create_all()
    read_token = "ht_preset_read"
    start_token = "ht_preset_start"
    policy_token = "ht_preset_policy"
    tokens = ",".join(
        [
            f"reader:arc:read:{hash_service_token(read_token)}",
            f"starter:arc:start:{hash_service_token(start_token)}",
            f"policy:arc:policy:{hash_service_token(policy_token)}",
        ]
    )
    settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="preset-test-secret",
        ARC_SERVICE_TOKENS=tokens,
    )
    try:
        with TestClient(create_app(settings=settings, db=db)) as client:
            url = "/api/v1/arc/evolution/preset"
            assert client.post(url, json={"preset": "production_3slot"}).status_code == 401
            assert (
                client.post(
                    url,
                    headers={"X-HyperTrade-Service-Token": read_token},
                    json={"preset": "production_3slot"},
                ).status_code
                == 403
            )
            assert (
                client.post(
                    url,
                    headers={"X-HyperTrade-Service-Token": start_token},
                    json={"preset": "production_3slot"},
                ).status_code
                == 403
            )
            policy_headers = {"X-HyperTrade-Service-Token": policy_token}
            assert (
                client.post(
                    url,
                    headers=policy_headers,
                    json={"preset": "production_3slot", "unexpected": True},
                ).status_code
                == 422
            )
            unknown = client.post(
                url,
                headers=policy_headers,
                json={"preset": "not_a_real_preset"},
            )
            assert unknown.status_code == 400
            applied = client.post(
                url,
                headers=policy_headers,
                json={"preset": "production_3slot"},
            )
            assert applied.status_code == 200, applied.text
            body = applied.json()
            assert body["revision"] == 1
            for key, value in EVOLUTION_PRESETS["production_3slot"].items():
                assert body["config"][key] == value
    finally:
        reset_store()


def test_arc_evolution_loop_applies_bootstrap_preset_once_before_tick(
    evo_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        DEEPSEEK_API_KEY="",
        ARC_EVOLUTION_BOOTSTRAP_PRESET="production_3slot",
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)

    seen_configs: list[dict[str, Any]] = []

    def fake_tick(self: EvolutionService, now: datetime | None = None) -> dict[str, Any]:
        seen_configs.append(self.status()["config"])
        return {"status": "no_action"}

    async def stop_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(EvolutionService, "tick", fake_tick)
    monkeypatch.setattr(worker.asyncio, "sleep", stop_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.arc_evolution_loop(evo_db))

    assert len(seen_configs) == 1
    assert seen_configs[0]["launch_enabled"] is True
    assert seen_configs[0]["exploration_provider"] == "rule_tweak"
    assert seen_configs[0]["paper_review_mode"] == "agent"


def test_effective_validation_criteria_scales_shortened_and_coarse_timeframes() -> None:
    base = ARCSuccessCriteriaV1(
        min_oos_net_return=Decimal("1E-8"),
        min_oos_sharpe=Decimal("0"),
        max_drawdown=Decimal("0.2"),
        min_trades=30,
        required_validation_policy="arc_windowed_v1",
    )
    full_1h = effective_validation_criteria(base, validation_days=60, timeframe="1H")
    assert full_1h.min_trades == 30

    short_20d_1h = effective_validation_criteria(base, validation_days=20, timeframe="1H")
    assert short_20d_1h.min_trades == 10

    daily_60d = effective_validation_criteria(base, validation_days=60, timeframe="1D")
    assert daily_60d.min_trades == 10

    daily_20d = effective_validation_criteria(base, validation_days=20, timeframe="1D")
    assert 3 <= daily_20d.min_trades <= 10

    four_hour_60d = effective_validation_criteria(base, validation_days=60, timeframe="4H")
    assert four_hour_60d.min_trades == 15

    four_hour_20d = effective_validation_criteria(base, validation_days=20, timeframe="4H")
    assert four_hour_20d.min_trades == 5

    tiny_2d = effective_validation_criteria(base, validation_days=2, timeframe="1H")
    assert tiny_2d.min_trades == 3

    low_caller = base.model_copy(update={"min_trades": 2})
    scaled_low = effective_validation_criteria(low_caller, validation_days=20, timeframe="1H")
    assert scaled_low.min_trades == 2


def _make_review_controller(
    *,
    is_source_variant: bool,
    paper_initial_equity: Decimal,
    research_capital: str | None,
    symbol: str = "BTC-USDT-SWAP",
    validation_days: int = 60,
    trades: int = 40,
    timeframe: str = "1H",
) -> ARCController:
    code = "class Candidate: pass"
    windows = ResearchWindowsV1(
        as_of=datetime(2026, 9, 11, tzinfo=UTC).date(),
        development_days=40 if validation_days < 60 else 119,
        validation_days=validation_days,
    )
    evolution_context: dict[str, Any] = {
        "source_strategy_id": 107,
        "source_instance_id": "paper-parent-107",
        "source_code_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "cycle_id": "evo_1_1",
    }
    if research_capital is not None:
        evolution_context["research_capital"] = research_capital
    goal = ARCGoalV1(
        objective="variant review capital check",
        symbols=[symbol],
        timeframes=[timeframe],
        research_mode="avo",
        paper_review_required=True,
        paper_review_mode="agent",
        paper_initial_equity=paper_initial_equity,
        research_windows=windows,
        evolution_context=evolution_context if is_source_variant else None,
        success_criteria=effective_validation_criteria(
            EvolutionConfig().paper_criteria,
            validation_days=validation_days,
            timeframe=timeframe,
        ),
    )
    ctrl = ARCController(goal=goal)
    start, end = goal.research_windows.window("final")  # type: ignore[union-attr]
    spec: dict[str, Any] = {"symbol": symbol, "timeframe": timeframe}
    if is_source_variant:
        spec.update(
            {
                "is_source_variant": True,
                "parent_strategy_id": 107,
                "parent_manifest_sha256": "a" * 64,
                "parent_execution_identity_sha256": "e" * 64,
                "parameter_changes": {"fast_window": 12},
            }
        )
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="cand_1",
                candidate_id="cand_1",
                strategy_code=code,
                hypothesis="one-step neighbour",
                strategy_spec=spec,
            ).model_dump(mode="json")
        },
    )
    window = {
        "purpose": "final",
        "start_date": str(start),
        "end_date": str(end),
        "research_id": goal.research_id,
    }
    ctrl.projection.avo["baseline_final"] = {
        "backtest_id": "bt-base",
        "metrics": {
            "evaluation_window": window,
            "net_return": 0.05,
            "max_drawdown": 0.05,
            "sharpe": 1.2,
            "trades": trades,
        },
    }
    ctrl.apply_event(
        "bitpro_self_tested",
        {
            "attempt_id": "cand_1",
            "passed": True,
            "purpose": "final",
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "bitpro_strategy_id": "9002",
            "backtest_id": "bt-cand",
            "validation_id": "val_cand",
            "metrics": {
                "return_statistics": stats(),
                "net_return": 0.12,
                "sharpe": 1.8,
                "max_drawdown": 0.04,
                "trades": trades,
                "evaluation_window": window,
                "baseline_comparison": {"passed": True, "backtest_id": "bt-base"},
            },
        },
    )
    request_paper_review(ctrl)
    return ctrl


def test_evaluate_auto_review_approves_1000u_bound_variant_and_rejects_unbounded_or_mismatched(
    evo_db: Database,
) -> None:
    config = EvolutionConfig(enabled=True, paper_review_mode="agent", paper_capital=Decimal("100"))

    # Bound 1000U variant with matching research_capital passes even with paper_capital=100,
    # and shortened 20d window scales policy min_trades from 30 -> 10 so 14 trades pass.
    bound_1000 = _make_review_controller(
        is_source_variant=True,
        paper_initial_equity=Decimal("1000"),
        research_capital="1000",
        symbol="BTC-USDT-SWAP",
        validation_days=20,
        trades=14,
    )
    approved = evaluate_auto_review(bound_1000, config)
    assert approved["decision"] == "approve", approved
    assert approved["reasons"] == []

    # Non-variant candidate at 1000U is still rejected by config.paper_capital=100.
    non_variant_1000 = _make_review_controller(
        is_source_variant=False,
        paper_initial_equity=Decimal("1000"),
        research_capital=None,
        symbol="ETH-USDT-SWAP",
    )
    rejected_non_variant = evaluate_auto_review(non_variant_1000, config)
    assert rejected_non_variant["decision"] == "reject"
    assert "automatic_paper_capital_limit" in rejected_non_variant["reasons"]

    # Bound variant with mismatched research_capital vs paper_initial_equity is rejected.
    mismatched = _make_review_controller(
        is_source_variant=True,
        paper_initial_equity=Decimal("1000"),
        research_capital="500",
        symbol="SOL-USDT-SWAP",
    )
    rejected_mismatch = evaluate_auto_review(mismatched, config)
    assert rejected_mismatch["decision"] == "reject"
    assert "automatic_paper_capital_limit" in rejected_mismatch["reasons"]

    # Bound variant missing research_capital at 1000U falls back to paper_capital=100 and rejects.
    unbound_variant = _make_review_controller(
        is_source_variant=True,
        paper_initial_equity=Decimal("1000"),
        research_capital=None,
        symbol="XRP-USDT-SWAP",
    )
    rejected_unbound = evaluate_auto_review(unbound_variant, config)
    assert rejected_unbound["decision"] == "reject"
    assert "automatic_paper_capital_limit" in rejected_unbound["reasons"]


class _FakeBitProPipelineClient:
    """Fake BitPro MCP client covering scan, rule_tweak backtests, cost check, and paper start."""

    def __init__(self, *, now: datetime) -> None:
        self.parent_id = 107
        self.parent_code = "class NativeParent107: pass\n"
        self.parent_capital = 1000.0
        self.manifest_sha = "a" * 64
        self.identity_sha = "e" * 64
        # Listed 64 days before `as_of` (2026-09-11) with 48h warmup + 1d slack => 60 usable days
        # => research_windows_for_parent yields development=40d, validation=20d.
        as_of = now.astimezone(UTC).date() - timedelta(days=1)
        listed_dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) - timedelta(days=64)
        self.history_start_ms = int(listed_dt.timestamp() * 1000)
        self.variants: dict[int, dict[str, Any]] = {}
        self.next_variant_id = 9001
        self.backtests_started: list[dict[str, Any]] = []
        self.backtest_jobs: dict[str, dict[str, Any]] = {}
        self.paper_configured: list[dict[str, Any]] = []
        self.paper_started: list[dict[str, Any]] = []

    def paper_strategy_performance(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "strategies": [
                {
                    "strategy_id": self.parent_id,
                    "strategy_name": "parent-107",
                    "mode": "paper",
                    "timeframe": "1H",
                }
            ]
        }

    def paper_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "strategy_id": self.parent_id,
            "instance_id": "paper-parent-107",
            "strategy_version": "v1",
            "config_version": "c1",
            "status": "running",
            "trade_count": 2,
            "strategy": {"symbols": ["BTC-USDT-SWAP"]},
            "session": {"started_at": "2026-09-10T00:00:00Z"},
        }

    def strategy_trades(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 1,
                "strategy_id": self.parent_id,
                "timestamp": int(datetime(2026, 9, 10, 6, tzinfo=UTC).timestamp() * 1000),
                "symbol": "BTC-USDT-SWAP",
                "side": "buy",
                "type": "market",
                "price": 60000.0,
                "quantity": 0.01,
                "fee": 0.3,
                "pnl": 4.2,
            }
        ]

    def strategy_get(self, *, strategy_id: int) -> dict[str, Any]:
        if int(strategy_id) == self.parent_id:
            return {
                "status": "ok",
                "strategy": {
                    "id": self.parent_id,
                    "script_content": self.parent_code,
                    "config": {
                        "timeframe": "1H",
                        "initial_capital": self.parent_capital,
                        "fast_window": 10,
                        "slow_window": 30,
                        "stop_loss_pct": 0.02,
                    },
                },
            }
        variant = self.variants[int(strategy_id)]
        return {
            "status": "ok",
            "strategy": {
                "id": int(strategy_id),
                "script_content": variant["script_content"],
                "config": variant["config"],
                "status": variant["status"],
            },
        }

    def strategy_research_variant_policy(self, *, strategy_id: int) -> dict[str, Any]:
        return {
            "contract_version": "strategy_research_variant_policy.v1",
            "parent_strategy_id": self.parent_id,
            "parent_manifest_sha256": self.manifest_sha,
            "parent_execution_identity_sha256": self.identity_sha,
            "variant_creation_supported": True,
            "authorized_parameters": [
                {"key": "fast_window", "type": "integer", "min": 5, "max": 50},
                {"key": "slow_window", "type": "integer", "min": 20, "max": 200},
                {"key": "stop_loss_pct", "type": "number", "min": 0.005, "max": 0.1},
            ],
            "relay": {
                "role": "parent",
                "plan_state": "none",
                "blocks_evolution": False,
                "seats": {"total": 3, "used": 0, "free": 3, "queued": 0, "open": 3},
            },
            "baseline_backtest": {
                "supported": True,
                "policy": "v1",
                "warmup_policy_bars": 500,
                "warmup_min_bars": 48,
                "history_start_ms": self.history_start_ms,
            },
        }

    def strategy_research_variant_create(
        self,
        *,
        strategy_id: int,
        expected_parent_manifest_sha256: str,
        expected_parent_execution_identity_sha256: str,
        idempotency_key: str,
        parameter_changes: dict[str, int | float],
        purpose: str = "candidate",
        structural_changes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for existing in self.variants.values():
            if existing["idempotency_key"] == idempotency_key:
                sid = existing["id"]
                cost_hash = existing["config"]["_research_cost_policy"]["hash"]
                return {
                    "contract_version": "strategy_research_variant.v1",
                    "parent_strategy_id": strategy_id,
                    "parent_manifest_sha256": expected_parent_manifest_sha256,
                    "purpose": purpose,
                    "status": "stopped",
                    "candidate_strategy_id": sid,
                    "strategy": {
                        "id": sid,
                        "script_content": self.parent_code,
                        "config": existing["config"],
                    },
                    "cost_receipt": {"cost_policy_hash": cost_hash},
                }
        sid = self.next_variant_id
        self.next_variant_id += 1
        cfg = _frozen_cost_config(
            **{
                "timeframe": "1H",
                "initial_capital": self.parent_capital,
                "fast_window": 10,
                "slow_window": 30,
                "stop_loss_pct": 0.02,
                **parameter_changes,
            }
        )
        self.variants[sid] = {
            "id": sid,
            "purpose": purpose,
            "idempotency_key": idempotency_key,
            "script_content": self.parent_code,
            "config": cfg,
            "status": "stopped",
        }
        return {
            "contract_version": "strategy_research_variant.v1",
            "parent_strategy_id": strategy_id,
            "parent_manifest_sha256": expected_parent_manifest_sha256,
            "purpose": purpose,
            "status": "stopped",
            "candidate_strategy_id": sid,
            "strategy": {"id": sid, "script_content": self.parent_code, "config": cfg},
            "cost_receipt": {"cost_policy_hash": cfg["_research_cost_policy"]["hash"]},
        }

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        self.backtests_started.append(dict(kwargs))
        sid = int(kwargs["strategy_id"])
        variant = self.variants[sid]
        is_baseline = variant["purpose"] == "baseline"
        cost_hash = variant["config"]["_research_cost_policy"]["hash"]
        bt_id = f"bt-{sid}-{len(self.backtests_started)}"
        job_id = f"job-{bt_id}"
        snapshot = {
            "runtime_sha256": "r" * 64,
            "cost_policy_hash": cost_hash,
            "initial_capital": kwargs["initial_capital"],
            "symbols": ["BTC-USDT-SWAP"],
            "timeframes": [kwargs["timeframe"]],
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
        }
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode()
        ).hexdigest()
        metrics = {
            "return_statistics": stats(),
            # Baseline has lower return/sharpe than candidate so candidate beats baseline strictly,
            # while 14 trades tests effective_validation_criteria scaling on the 20d window.
            "net_return": 0.08 if is_baseline else 0.14,
            "sharpe": 1.3 if is_baseline else 1.9,
            "max_drawdown": 0.06 if is_baseline else 0.04,
            "trades": 14,
        }
        result = {
            "status": "ok",
            "backtest_id": bt_id,
            "metrics": metrics,
            "job": {
                "job_id": job_id,
                "strategy_id": sid,
                "input_snapshot_hash": snapshot_hash,
                "status": "completed",
                "strategy_input_snapshot": snapshot,
                "verified_data_binding": {
                    "version": "verified_backtest_data.v3",
                    "entries": [{"verified_snapshot_id": "vbs-1", "manifest_sha256": "d" * 64}],
                },
            },
        }
        self.backtest_jobs[job_id] = result
        return result

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]:
        return self.backtest_jobs[job_id]

    def paper_configure_reviewed(self, **kwargs: Any) -> dict[str, Any]:
        self.paper_configured.append(dict(kwargs))
        sid = int(kwargs["strategy_id"])
        variant = self.variants[sid]
        strategy_version = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    {"script_content": variant["script_content"]},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        return {
            "status": "ok",
            "paper": {
                "configured": True,
                "strategy_id": sid,
                "instance_id": f"paper-variant-{sid}",
                "guard_version": "1",
                "review_hash": kwargs["review_hash"],
                "code_sha256": kwargs["code_sha256"],
                "strategy_version": strategy_version,
                "config_version": "cfg-v1",
            },
        }

    def paper_start_reviewed(self, **kwargs: Any) -> dict[str, Any]:
        self.paper_started.append(dict(kwargs))
        sid = int(kwargs["strategy_id"])
        return {
            "status": "ok",
            "paper": {
                "started": True,
                "strategy_id": sid,
                "instance_id": kwargs["instance_id"],
                "guard_version": "1",
                "review_hash": kwargs["review_hash"],
                "code_sha256": kwargs["code_sha256"],
                "config_version": kwargs["config_version"],
            },
        }


def test_end_to_end_variant_production_pipeline_from_tick_to_paper_observing(
    evo_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    client = _FakeBitProPipelineClient(now=now)

    # Simulate production missing-14d-window (launch_enabled=True, launch_days=0 covers it).
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_windows",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("paper_session_younger_than_14d")),
    )
    monkeypatch.setattr(
        "hypertrade.arc.evolution.collect_observed_long_window",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("observed_gap")),
    )
    # Prevent any real LLM provider call during rule_tweak AVO execution.
    monkeypatch.setattr(
        "hypertrade.arc.avo.ProviderRuntime",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("rule_tweak must not call LLM")),
    )
    # Route self_test and auto_review cost checks through the same fake BitPro client.
    monkeypatch.setattr("hypertrade.arc.self_test.BitProToolAdapter", lambda *a, **k: client)
    monkeypatch.setattr(
        "hypertrade.arc.auto_review.read_candidate_source",
        lambda sid: client.strategy_get(strategy_id=sid)["strategy"],
    )

    service = EvolutionService(evo_db, client=client)
    bootstrapped = service.ensure_bootstrap_preset("production_3slot")
    assert bootstrapped is not None
    assert bootstrapped["config"]["paper_capital"] == "100"

    # 1. Evolution scan creates AVO mission bound to 1000U parent and 20d shortened window.
    tick_result = service.tick(now)
    assert tick_result["status"] == "research_created", tick_result
    mission_id = tick_result["payload"]["mission_id"]

    ctrl = get_controller(mission_id)
    assert ctrl is not None
    goal = ctrl.projection.goal
    assert goal is not None
    assert goal.provider_name == "rule_tweak"
    assert goal.paper_initial_equity == Decimal("1000.0")
    assert goal.evolution_context["research_capital"] == "1000.0"
    assert goal.research_windows is not None
    assert goal.research_windows.validation_days == 20
    assert goal.success_criteria.min_trades == 10

    # 2. AVO loop runs rule_tweak end-to-end and submits final candidate to paper_review_ready.
    avo_result = run_pending_avo_once()
    assert avo_result["status"] == "paper_review_ready", avo_result
    assert client.backtests_started
    assert all(float(bt["initial_capital"]) == 1000.0 for bt in client.backtests_started)

    # 3. Auto-review approves the 1000U bound variant and provisions Paper -> paper_observing.
    resolver = ARCPaperIncubationResolver(client=client)  # type: ignore[arg-type]
    review_result = auto_review_once(evo_db, resolver=resolver)
    assert review_result == {"status": "paper_observing", "mission_id": mission_id}

    final_ctrl = get_controller(mission_id)
    assert final_ctrl is not None
    assert final_ctrl.projection.state == "paper_observing"
    assert client.paper_configured and client.paper_configured[0]["initial_equity"] == 1000.0
    assert client.paper_started
    started_sid = client.paper_started[0]["strategy_id"]
    observing_attempt = next(
        a for a in final_ctrl.projection.attempts if a.state == "paper_observing"
    )
    assert observing_attempt.paper_instance_id == f"paper-variant-{started_sid}"
