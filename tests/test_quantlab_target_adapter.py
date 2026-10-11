"""Unit tests for QuantLab Market Target Adapter and Self-Healing Evolution."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from hypertrade.paper.race_judge import RaceJudgeDaemon, RacePairRecord
from hypertrade.paper.registry import StrategyRecord, StrategyRegistry
from hypertrade.paper.self_healing import (
    SelfHealingEvolutionEngine,
    generate_7d_attribution_report,
    heal_quantlab_strategy,
    mutate_strategy_parameters,
)
from hypertrade.paper.stage_gate import StrategyStage
from hypertrade.targets.quantlab import (
    QUANTLAB_TARGET_ID,
    QUANTLAB_TARGET_PROFILE,
    QuantLabTargetAdapter,
    quantlab_adapter_factory,
    register_quantlab_target,
)
from hypertrade.targets.registry import (
    get_market_target,
    registered_market_targets,
)


def test_quantlab_target_profile_and_capabilities() -> None:
    register_quantlab_target(replace=True)
    binding = get_market_target(QUANTLAB_TARGET_ID)
    profile = binding.profile

    assert profile == QUANTLAB_TARGET_PROFILE
    assert profile.target_id == "quantlab"
    assert profile.display_name == "QuantLab 量化交易工作台"
    assert profile.transport == "mcp_contract_v1"
    assert profile.tool_contract == "market-evolution.v1"
    assert profile.venue == "multi_asset"
    assert profile.market_type == "cash"
    assert profile.quote_currency == "CNY"
    assert profile.strategy_id_format == "string"

    assert profile.capabilities.backtest is True
    assert profile.capabilities.paper_launch is True
    assert profile.capabilities.running_inventory is True
    assert profile.capabilities.execution_ledger is True
    assert profile.capabilities.live_preflight is False

    assert profile.calendar.mode == "sessions"
    assert profile.calendar.session_open == "09:30"
    assert profile.calendar.session_close == "15:00"
    assert profile.calendar.evidence_window_days == 14

    registered = registered_market_targets()
    assert any(t.target_id == "quantlab" for t in registered)

    factory_adapter = quantlab_adapter_factory(simulation=True)
    assert isinstance(factory_adapter, QuantLabTargetAdapter)


def test_quantlab_adapter_lifecycle_and_ports() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)

    # Create strategy
    created = adapter.strategy_create(
        strategy_id="quantlab:alpha_trend_01",
        name="A-share Alpha Trend 01",
        symbols=["600519.SH", "000858.SZ"],
        timeframe="1D",
        config={"fast_period": 10, "slow_period": 30},
        mode="paper",
    )
    assert created["strategy_id"] == "quantlab:alpha_trend_01"
    assert created["status"] == "created"
    assert len(created["code_sha256"]) == 64

    # List running strategies
    handles = adapter.list_running_strategies()
    assert any(h.strategy_id == "quantlab:alpha_trend_01" for h in handles)

    # Configure and start paper trading
    cfg = adapter.configure_paper(
        candidate_key="quantlab:alpha_trend_01",
        strategy_id="quantlab:alpha_trend_01",
        capital=200000.0,
    )
    assert cfg["status"] == "configured"
    assert cfg["capital"] == 200000.0

    started = adapter.start_paper(
        candidate_key="quantlab:alpha_trend_01",
        strategy_id="quantlab:alpha_trend_01",
    )
    assert started["status"] == "running"
    assert started["target"] == "quantlab"

    # Query snapshot
    snap = adapter.get_session_snapshot(strategy_id="quantlab:alpha_trend_01")
    assert snap.strategy_id == "quantlab:alpha_trend_01"
    assert snap.status == "running"
    assert snap.equity == 200000.0

    # Read equity series
    page = adapter.read_equity_series(snap.instance_id, start_ms=0, end_ms=9999999999999)
    assert page.strategy_id == "quantlab:alpha_trend_01"
    assert len(page.points) > 0
    assert page.complete is True

    # Stop paper trading
    stopped = adapter.stop_paper(
        candidate_key="quantlab:alpha_trend_01",
        strategy_id="quantlab:alpha_trend_01",
    )
    assert stopped["status"] == "stopped"


def test_quantlab_adapter_backtest_and_relay() -> None:
    adapter = QuantLabTargetAdapter(simulation=True)

    # Start and fetch backtest
    bt_start = adapter.backtest_start_job(
        strategy_id="quantlab:alpha_trend_01",
        timeframe="1D",
    )
    assert bt_start["status"] == "running"
    job_id = bt_start["job_id"]

    bt_res = adapter.backtest_get_job(job_id)
    assert bt_res["status"] == "completed"
    metrics = bt_res["metrics"]
    assert metrics["win_rate"] >= 0.40
    assert metrics["annualized_sharpe"] > 1.0
    assert metrics["total_trades"] > 0

    # Relay status & control
    status = adapter.paper_relay_status("quantlab:alpha_trend_01")
    assert status["parent_strategy_id"] == "quantlab:alpha_trend_01"
    assert status["eligible"] is True

    ctrl = adapter.paper_relay_control("quantlab:alpha_trend_01", action="adopt")
    assert ctrl["status"] == "success"
    assert ctrl["action"] == "adopt"


def test_ashare_quantlab_mutation_rules() -> None:
    parent_params = {
        "fast_period": 10,
        "slow_period": 30,
        "hard_stop_loss_pct": "0.06",
        "position_sizing_pct": 25.0,
    }
    mutated, constraints = mutate_strategy_parameters(
        strategy_type="a_share_alpha_trend",
        parent_params=parent_params,
        strategy_name="[A股][日线][量化] 多因子动量轮动 · 10万",
    )

    assert mutated["allow_short"] is False
    assert mutated["min_holding_days"] >= 1
    assert mutated["position_sizing_pct"] <= 30.0
    assert mutated["fast_period"] >= 15
    assert mutated["slow_period"] >= 40
    assert Decimal(str(mutated["stop_loss_pct"])) < Decimal("0.06")

    assert "smooth_ashare_trend_filters_and_enforce_t_plus_one" in constraints
    assert "cap_ashare_cash_exposure_and_forbid_short_selling" in constraints


def test_ashare_7d_attribution_report() -> None:
    report = generate_7d_attribution_report(
        strategy_name="[A股][日线][量化] 沪深300多因子轮动",
        strategy_type="a_share_multi_factor",
        parameters={"fast_period": 15, "slow_period": 40, "stop_loss_pct": "0.048"},
        metrics={"win_rate": 0.62, "simulated_trades": 40},
        strategy_id="quantlab:multi_factor_01",
    )

    assert report["schema_version"] == "paper_attribution.v1"
    dims = report["dimensions"]

    assert report["causal_conclusion"] == "not_established"
    assert all(d["state"] == "unknown" and d["metrics"] == {} for d in dims.values())


def test_self_healing_quantlab_strategy() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)
        adapter = QuantLabTargetAdapter(simulation=True)
        engine = SelfHealingEvolutionEngine(
            registry=registry,
            history_file=hist_file,
            quantlab_adapter=adapter,
        )

        parent_sid = "quantlab:momentum_01"
        rec = StrategyRecord(
            strategy_id=parent_sid,
            strategy_type="a_share_alpha_trend",
            name="[A股][日线][量化] 沪深300动量增强 · Gen 1 · 10万",
            parameters={
                "fast_period": 10,
                "slow_period": 30,
                "hard_stop_loss_pct": "0.06",
                "symbols": ["600519.SH", "000858.SZ"],
                "market_target": "quantlab",
                "strategy_code": "class ParentStrategy: pass",
            },
            stage=StrategyStage.DEGRADED,
            generation=1,
        )
        registry.register(rec)

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(True, "ok"),
        ):
            healed = engine.heal_strategy(parent_sid)

        assert healed is not None
        assert healed.parent_strategy_id == parent_sid
        assert healed.offspring_strategy_id == "quantlab:momentum_01_gen2"
        assert healed.generation == 2
        assert healed.target_id == "quantlab"
        assert healed.quantlab_deployed is True
        assert healed.quantlab_strategy_id == "quantlab:momentum_01_gen2"
        assert healed.quantlab_instance_id is not None
        assert healed.validation_metrics["source"] == "quantlab_backtest"

        # Check offspring record in registry
        offspring_rec = registry.get("quantlab:momentum_01_gen2")
        assert offspring_rec is not None
        assert offspring_rec.stage == StrategyStage.PAPER_OBSERVING
        assert offspring_rec.parameters["allow_short"] is False
        assert offspring_rec.parameters["min_holding_days"] >= 1


def test_heal_quantlab_strategy_helper_function() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        reg_file = Path(tmpdir) / "registry.json"
        hist_file = Path(tmpdir) / "history.json"
        registry = StrategyRegistry(storage_path=reg_file)
        adapter = QuantLabTargetAdapter(simulation=True)
        engine = SelfHealingEvolutionEngine(
            registry=registry,
            history_file=hist_file,
            quantlab_adapter=adapter,
        )

        with patch(
            "hypertrade.paper.self_healing.dispatch_reflexion_alert",
            return_value=(True, "ok"),
        ):
            healed = heal_quantlab_strategy(
                "quantlab:stock_grid_01",
                snapshot_or_config={
                    "name": "QuantLab Stock Grid",
                    "strategy_type": "a_share_alpha_trend",
                    "config": {
                        "fast_period": 10,
                        "slow_period": 30,
                        "symbols": ["600519.SH"],
                        "strategy_code": "class ParentGridStrategy: pass",
                    },
                },
                engine=engine,
            )

        assert healed.offspring_strategy_id == "quantlab:stock_grid_01_gen2"
        assert healed.quantlab_deployed is True
        assert healed.target_id == "quantlab"


class _ReceiptQuantLabAdapter:
    def __init__(
        self,
        *,
        start_status: str = "running",
        reconcile_running: bool = False,
        backtest_status: str = "completed",
    ) -> None:
        self.start_status = start_status
        self.reconcile_running = reconcile_running
        self.backtest_status = backtest_status
        self.create_fields: dict = {}
        self.configure_fields: dict = {}
        self.start_fields: dict = {}

    def backtest_start_job(self, **kwargs):
        return {"job_id": "bt-1", "status": "running"}

    def backtest_get_job(self, job_id):
        return {
            "job_id": job_id,
            "status": self.backtest_status,
            "metrics": {
                "win_rate": 0.55,
                "profit_factor": 1.2,
                "annualized_sharpe": 0.8,
                "max_drawdown_pct": 0.1,
                "total_trades": 30,
            },
        }

    def strategy_create(self, **fields):
        self.create_fields = fields
        return {"status": "created", "strategy_id": fields["strategy_id"]}

    def paper_configure(self, **fields):
        self.configure_fields = fields
        return {
            "status": "configured",
            "strategy_id": fields["strategy_id"],
            "instance_id": "paper-verified-1",
        }

    def paper_start(self, **fields):
        self.start_fields = fields
        if self.start_status == "raise":
            raise TimeoutError("unknown remote outcome")
        return {
            "status": self.start_status,
            "strategy_id": fields["strategy_id"],
            "instance_id": fields["instance_id"],
        }

    def paper_snapshot(self, **fields):
        return {
            "status": "running" if self.reconcile_running else "configured",
            "strategy_id": fields["strategy_id"],
            "instance_id": fields.get("instance_id") or "paper-verified-1",
        }


def test_quantlab_self_healing_requires_verified_configure_and_start_receipts() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = StrategyRegistry(storage_path=Path(tmpdir) / "registry.json")
        adapter = _ReceiptQuantLabAdapter(start_status="unknown")
        engine = SelfHealingEvolutionEngine(
            registry=registry,
            history_file=Path(tmpdir) / "history.json",
            quantlab_adapter=adapter,
        )
        registry.register(
            StrategyRecord(
                strategy_id="42",
                strategy_type="a_share_alpha_trend",
                name="A share opaque id",
                parameters={
                    "market_target": "quantlab",
                    "symbols": ["600519.SH"],
                    "timeframe": "1D",
                    "strategy_code": "class ParentOpaqueStrategy: pass",
                },
                stage=StrategyStage.DEGRADED,
            )
        )
        active_before = len(registry.build_active_strategies())
        healed = engine.heal_strategy("42")
        assert healed is not None
        assert healed.target_id == "quantlab"
        assert healed.quantlab_deployed is False
        assert healed.quantlab_instance_id is None
        assert registry.get(healed.offspring_strategy_id).stage == StrategyStage.INCUBATING
        assert adapter.start_fields["instance_id"] == "paper-verified-1"
        assert adapter.create_fields["code"] == "class ParentOpaqueStrategy: pass"
        assert adapter.configure_fields["idempotency_key"] == (
            "self_heal:quantlab:42:gen2:configure"
        )
        assert adapter.start_fields["idempotency_key"] == (
            "self_heal:quantlab:42:gen2:start"
        )
        assert registry.get(healed.offspring_strategy_id).is_active is False
        assert len(registry.build_active_strategies()) == active_before


def test_quantlab_self_healing_reconciles_unknown_start_outcome() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = StrategyRegistry(storage_path=Path(tmpdir) / "registry.json")
        adapter = _ReceiptQuantLabAdapter(
            start_status="raise", reconcile_running=True
        )
        engine = SelfHealingEvolutionEngine(
            registry=registry,
            history_file=Path(tmpdir) / "history.json",
            quantlab_adapter=adapter,
        )
        registry.register(
            StrategyRecord(
                strategy_id="42",
                strategy_type="a_share_alpha_trend",
                name="A share opaque id",
                parameters={
                    "market_target": "quantlab",
                    "symbols": ["600519.SH"],
                    "timeframe": "1D",
                    "strategy_code": "class ParentOpaqueStrategy: pass",
                },
                stage=StrategyStage.DEGRADED,
            )
        )
        active_before = len(registry.build_active_strategies())
        healed = engine.heal_strategy("42")
        assert healed is not None
        assert healed.quantlab_deployed is True
        assert healed.quantlab_instance_id == "paper-verified-1"
        assert registry.get(healed.offspring_strategy_id).stage == StrategyStage.PAPER_OBSERVING
        assert len(registry.build_active_strategies()) == active_before + 1


def test_quantlab_unknown_backtest_blocks_every_remote_write() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = StrategyRegistry(storage_path=Path(tmpdir) / "registry.json")
        adapter = _ReceiptQuantLabAdapter(backtest_status="running")
        engine = SelfHealingEvolutionEngine(
            registry=registry,
            history_file=Path(tmpdir) / "history.json",
            quantlab_adapter=adapter,
        )
        registry.register(
            StrategyRecord(
                strategy_id="42",
                strategy_type="a_share_alpha_trend",
                name="A share opaque id",
                parameters={
                    "market_target": "quantlab",
                    "symbols": ["600519.SH"],
                    "timeframe": "1D",
                    "strategy_code": "class ParentOpaqueStrategy: pass",
                },
                stage=StrategyStage.DEGRADED,
            )
        )
        active_before = len(registry.build_active_strategies())
        healed = engine.heal_strategy("42")
        assert healed is not None
        assert healed.validation_metrics["source"] == "quantlab_backtest_unavailable"
        assert healed.quantlab_deployed is False
        assert adapter.create_fields == {}
        assert adapter.configure_fields == {}
        assert adapter.start_fields == {}
        preview = registry.get(healed.offspring_strategy_id)
        assert preview is not None
        assert preview.is_active is False
        assert preview.stage == StrategyStage.INCUBATING
        assert len(registry.build_active_strategies()) == active_before


def test_race_judge_with_quantlab_string_ids() -> None:
    rec = RacePairRecord(
        parent_strategy_id="quantlab:alpha_01",
        challenger_strategy_id="quantlab:alpha_01_gen2",
        generation=2,
        parent_name="Parent Alpha",
        challenger_name="Challenger Alpha",
        state="observing",
        eligible=True,
        reason="测试评估",
        proof_sha256="abc123sha",
        observed_hours=336,
        target_hours=336,
        target_id="quantlab",
    )
    serialized = rec.to_dict()
    assert serialized["parent_strategy_id"] == "quantlab:alpha_01"
    assert serialized["challenger_strategy_id"] == "quantlab:alpha_01_gen2"
    assert serialized["target_id"] == "quantlab"

    deserialized = RacePairRecord.from_dict(serialized)
    assert deserialized.parent_strategy_id == "quantlab:alpha_01"
    assert deserialized.challenger_strategy_id == "quantlab:alpha_01_gen2"
    assert deserialized.target_id == "quantlab"

    with tempfile.TemporaryDirectory() as tmpdir:
        import json

        hist_file = Path(tmpdir) / "healing_history.json"
        state_file = Path(tmpdir) / "race_state.json"
        history_data = [
            {
                "parent_strategy_id": "quantlab:parent_01",
                "quantlab_strategy_id": "quantlab:parent_01_gen2",
                "generation": 2,
                "quantlab_deployed": True,
            }
        ]
        hist_file.write_text(json.dumps(history_data), encoding="utf-8")
        register_quantlab_target(
            lambda: QuantLabTargetAdapter(simulation=True), replace=True
        )

        daemon = RaceJudgeDaemon(
            history_file=hist_file,
            state_file=state_file,
        )

        pairs = daemon.discover_active_pairs()
        assert len(pairs) == 1
        assert pairs[0] == (
            "quantlab",
            "quantlab:parent_01",
            "quantlab:parent_01_gen2",
            2,
        )

        pair_record = daemon.evaluate_pair(
            "quantlab:parent_01",
            "quantlab:parent_01_gen2",
            2,
            target_id="quantlab",
        )
        assert pair_record.parent_strategy_id == "quantlab:parent_01"
        assert pair_record.challenger_strategy_id == "quantlab:parent_01_gen2"
        assert pair_record.target_id == "quantlab"
