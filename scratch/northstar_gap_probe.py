"""Empirical gap probe: current HyperTrade vs North Star + M0.

Measures what the code actually does today, not what docs claim.
Prints a machine-readable JSON summary at the end.

    uv run python scratch/northstar_gap_probe.py
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend" / "src"))


def _ok(name: str, passed: bool, detail: str, **extra: Any) -> dict[str, Any]:
    row = {"name": name, "passed": passed, "detail": detail}
    row.update(extra)
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {name}")
    print(f"         {detail}")
    return row


def probe_m0_controller() -> list[dict[str, Any]]:
    print("\n=== M0 产品主路径 ===")
    rows: list[dict[str, Any]] = []
    try:
        importlib.import_module("hypertrade.research.autonomous_controller")
        rows.append(_ok("AutonomousResearchController 模块存在", True, "可 import"))
    except ModuleNotFoundError as exc:
        rows.append(
            _ok(
                "AutonomousResearchController 模块存在",
                False,
                f"合同要求的控制器不存在: {exc}",
            )
        )
    try:
        from hypertrade.research.schemas import ResearchGoalV1  # type: ignore

        rows.append(_ok("ResearchGoalV1 合同存在", True, str(ResearchGoalV1)))
    except Exception:
        rows.append(
            _ok(
                "ResearchGoalV1 合同存在",
                False,
                "M0 合同的 ResearchGoalV1 未落地；现有的是 ARCGoalV1",
            )
        )
    tree = list((ROOT / "backend" / "src" / "hypertrade").rglob("*.py"))
    hits = [
        p
        for p in tree
        if "AutonomousResearchController" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    rows.append(
        _ok(
            "代码树出现 AutonomousResearchController",
            bool(hits),
            f"命中文件: {[str(p.relative_to(ROOT)) for p in hits] or '无'}",
        )
    )
    return rows


def probe_codegen() -> list[dict[str, Any]]:
    print("\n=== Gate 1 生成能力 ===")
    from hypertrade.research.codegen import FAMILIES, generate_strategy
    from hypertrade.research.orchestrator import _compile_strategy

    rows: list[dict[str, Any]] = []
    cases = [
        ("momentum_breakout", "TREND", "高波动环境下 ATR 通道突破捕捉趋势启动", "突破 ATR 上轨"),
        ("mean_reversion_short_only", "MEAN_REVERSION", "价格偏离均值 2 个标准差后回归，仅做空", "z-score 超过 2 时做空"),
        ("orderbook_imbalance_hft", "MICROSTRUCTURE", "短期涨跌幅变化率反转，多空双向", "ROC 超过阈值"),
        ("funding_rate_arbitrage", "CARRY", "唐奇安通道新高延续，多空双向", "突破前 20 根最高价"),
        ("volatility_regime_switching", "VOLATILITY", "RSI 超买超卖切换", "RSI 低于超卖线"),
    ]
    logics: dict[str, str] = {}
    families: list[str] = []
    for key, category, hypothesis, entry in cases:
        spec = {
            "schema_version": "research_strategy_spec.v1",
            "mandate_id": "rman_probe",
            "strategy_key": key,
            "title": key,
            "hypothesis": hypothesis,
            "symbols": ["BTC"],
            "timeframes": ["1H"],
            "strategy_category": category,
            "entry_logic": entry,
            "exit_logic": "placeholder exit",
            "risk_conditions": ["bounded notional"],
            "data_requirements": ["ohlcv"],
            "parameter_bounds": {},
            "invalidation_conditions": ["insufficient data"],
        }
        code = _compile_strategy(spec)
        generated = generate_strategy(spec)
        logic = "\n".join(
            line
            for line in code.split("\n")
            if not line.startswith("class ") and not line.strip().startswith(("#", '"""'))
        )
        logics[key] = logic
        families.append(generated.family)
    unique = len(set(logics.values()))
    rows.append(
        _ok(
            "语义不同假设编译出不同策略逻辑",
            unique == len(cases),
            f"{len(cases)} 个 key → {unique} 种逻辑, 族={families}",
            unique_logics=unique,
            families=families,
            catalog_size=len(FAMILIES),
        )
    )
    rows.append(
        _ok(
            "策略族目录覆盖任意 Alpha",
            False,
            f"确定性目录只有 {len(FAMILIES)} 族，无法表达订单簿/资金费/跨品种等未建模假设",
            catalog_size=len(FAMILIES),
        )
    )
    return rows


def probe_arc_loop_honesty() -> list[dict[str, Any]]:
    print("\n=== ARC 循环诚实性 ===")
    rows: list[dict[str, Any]] = []
    from hypertrade.arc import router as arc_router
    from hypertrade.arc.contracts import ARCGoalV1, ARCSuccessCriteriaV1
    from hypertrade.arc.evidence import MIN_ADMISSIBLE_OOS_SHARPE, MIN_OUT_OF_SAMPLE_TRADES
    from hypertrade.arc.incubation import ARCPaperIncubationResolver, format_bitpro_strategy_name
    from hypertrade.arc.contracts import ARCCandidateAttemptV1, PaperPreauthorizationV1

    src = inspect.getsource(arc_router.run_autonomous_arc_loop)
    rows.append(
        _ok(
            "ARC 循环调用 UnifiedStrategyValidationService",
            "UnifiedStrategyValidation" in src,
            "晋级用的是 f'val_{attempt_id}' 本地字符串，未走 Sprint 129 统一验证漏斗"
            if "UnifiedStrategyValidation" not in src
            else "已接入统一验证",
        )
    )
    rows.append(
        _ok(
            "ARC 循环读取 success_criteria",
            "success_criteria" in src,
            f"目标里 min_oos_sharpe 默认 {ARCSuccessCriteriaV1().min_oos_sharpe}，"
            f"证据门禁用 {MIN_ADMISSIBLE_OOS_SHARPE} / 最少 {MIN_OUT_OF_SAMPLE_TRADES} 笔；"
            "循环源码不引用 success_criteria",
            goal_min_sharpe=str(ARCSuccessCriteriaV1().min_oos_sharpe),
            gate_min_sharpe=MIN_ADMISSIBLE_OOS_SHARPE,
        )
    )
    rows.append(
        _ok(
            "ARC Mission 持久化",
            "_ARC_MISSIONS" not in inspect.getsource(arc_router),
            "任务存在模块级 dict，进程重启即丢，不是 Sprint 123 的可重放 Mission 事件",
        )
    )

    attempt = ARCCandidateAttemptV1(
        attempt_id="att_probe",
        candidate_id="cand_probe",
        state="validated",
        hypothesis="probe",
        strategy_code="class X(BaseStrategy):\n    pass\n",
    )
    preauth = PaperPreauthorizationV1(symbols=["BTC-USDT-SWAP"])
    resolver = ARCPaperIncubationResolver()
    ok, paper_id, name, msg = resolver.resolve_and_provision_paper_trading(attempt, preauth)
    rows.append(
        _ok(
            "Paper 上线失败时不谎称成功",
            not (ok and paper_id and paper_id.startswith("bitpro_paper_") and "Successfully" in (msg or "")),
            f"BitPro 调用被 except: pass 吞掉后仍返回 ok={ok} id={paper_id} name={name}",
            paper_ok=ok,
            paper_id=paper_id,
            paper_name=name,
        )
    )
    hardcoded = format_bitpro_strategy_name("BTC-USDT-SWAP")
    rows.append(
        _ok(
            "模拟盘策略名反映真实逻辑",
            "20周期突破8%动态止损" not in hardcoded,
            f"命名被写死为 {hardcoded!r}，与候选族无关",
        )
    )
    inc_src = inspect.getsource(resolver.resolve_and_provision_paper_trading)
    rows.append(
        _ok(
            "ARC Paper 调用 configure/start",
            "paper_configure" in inc_src and "paper_start" in inc_src,
            "只尝试 strategy_create；Sprint 130 的 configure/start/observe/对账未接入",
        )
    )

    try:
        ARCGoalV1(objective="x", symbols=["BTC-USDT-SWAP"], live_allowed=True)
        live_locked = False
    except Exception:
        live_locked = True
    rows.append(
        _ok(
            "live_allowed 类型锁死为 False",
            live_locked,
            "这是有意安全边界，Gate 4/5 因此在类型层不可表达",
        )
    )
    return rows


def probe_two_pipelines() -> list[dict[str, Any]]:
    print("\n=== 双研究管道是否统一 ===")
    rows: list[dict[str, Any]] = []
    orch = (ROOT / "backend" / "src" / "hypertrade" / "research" / "orchestrator.py").read_text()
    arc = (ROOT / "backend" / "src" / "hypertrade" / "arc" / "router.py").read_text()
    rows.append(
        _ok(
            "研究编排器与 ARC 共用同一套回放证据",
            "replay_candidate" in orch and "backtest_start_job" not in orch,
            "orchestrator 仍走 BitPro backtest_start_job；ARC 走本地 replay_candidate。"
            "同一候选两条口径，无法比较",
        )
    )
    rows.append(
        _ok(
            "ARC 复用 Sprint 130 PaperIncubation",
            "AutonomousPaperIncubationService" in arc,
            "ARC 自写了 incubation.py，不走 Approval / DispatchIntent / reconciliation",
        )
    )
    rows.append(
        _ok(
            "ARC 复用 Sprint 125 Outcome Ledger",
            "StrategyOutcome" in arc or "outcome_ledger" in arc,
            "ARC 只写 Reflexion 内存账本，不落已结算 Outcome",
        )
    )
    return rows


def probe_flags_and_gates() -> list[dict[str, Any]]:
    print("\n=== 默认开关与 Gate 2–5 资产 ===")
    from hypertrade.config import Settings

    rows: list[dict[str, Any]] = []
    s = Settings()
    flags = {
        "mission_runtime_enabled": s.mission_runtime_enabled,
        "mission_runtime_worker_enabled": s.mission_runtime_worker_enabled,
        "research_triggers_enabled": s.research_triggers_enabled,
        "strategy_sandbox_enabled": s.strategy_sandbox_enabled,
        "world_model_defensive_actions_enabled": s.world_model_defensive_actions_enabled,
        "paper_enabled": s.paper_enabled,
        "monitor_scheduler_enabled": s.monitor_scheduler_enabled,
    }
    rows.append(
        _ok(
            "Mission 运行时默认开启",
            bool(flags["mission_runtime_enabled"] and flags["mission_runtime_worker_enabled"]),
            f"mission={flags['mission_runtime_enabled']} worker={flags['mission_runtime_worker_enabled']}",
            flags=flags,
        )
    )
    rows.append(
        _ok(
            "研究触发器默认开启",
            bool(flags["research_triggers_enabled"]),
            "Gate 2 要求按 regime/衰减自动启动研究；默认关闭",
        )
    )

    from hypertrade.arc.canary_vault import CanaryVaultPipeline
    from hypertrade.arc.contracts import LiveTradingMandateV1
    from hypertrade.research.outcome_ledger import StrategyOutcomeLedgerService
    from hypertrade.research.paper_incubation import AutonomousPaperIncubationService
    from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
    from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2

    rows.append(
        _ok(
            "Sprint 125–131 资产存在",
            True,
            "Outcome / ValidationV2 / PaperIncubation / RegimeShadow 类均可 import",
            assets=[
                StrategyOutcomeLedgerService.__name__,
                UnifiedStrategyValidationService.__name__,
                AutonomousPaperIncubationService.__name__,
                RegimeShadowAllocatorServiceV2.__name__,
                CanaryVaultPipeline.__name__,
                LiveTradingMandateV1.__name__,
            ],
        )
    )
    vault_src = inspect.getsource(CanaryVaultPipeline)
    rows.append(
        _ok(
            "CanaryVault 能下实盘单",
            "place_order" in vault_src or "live_order" in vault_src,
            "只是指标进阶/降级函数，无订单、无对账、无独立执行身份",
        )
    )
    return rows


def probe_seven_capabilities() -> list[dict[str, Any]]:
    print("\n=== 北极星七项能力（实现是否可调用） ===")
    rows: list[dict[str, Any]] = []
    checks = [
        (
            "理解市场",
            "hypertrade.portfolio.market_regime_v2",
            "MarketRegimeSnapshotServiceV2",
            "有概率快照服务，但是点查不是持续识别；跨资产缺口仍是 missing_data",
        ),
        (
            "理解策略",
            "hypertrade.research.strategy_cards",
            "StrategyCardService",
            "有 Card/lineage，但适用状态/衰减/Paper-Live 偏差未自动维护",
        ),
        (
            "自主研究",
            "hypertrade.arc.router",
            "run_autonomous_arc_loop",
            "ARC 循环可跑，但是内存态 + 6 族目录 + 未接统一验证",
        ),
        (
            "自主组合",
            "hypertrade.portfolio.regime_shadow",
            "RegimeShadowAllocatorServiceV2",
            "有约束模板与迟滞，生产曾 0 eligible；ARC portfolio 是相关阈值玩具",
        ),
        (
            "自主孵化",
            "hypertrade.research.paper_incubation",
            "AutonomousPaperIncubationService",
            "Sprint 130 路径完整但需人工 mandate；ARC 路径会在 BitPro 失败时谎称成功",
        ),
        (
            "授权内执行",
            "hypertrade.arc.canary_vault",
            "CanaryVaultPipeline",
            "schema + 指标函数在，live_allowed 锁死，无实盘写路径",
        ),
        (
            "持续进化",
            "hypertrade.research.outcome_ledger",
            "StrategyOutcomeLedgerService",
            "Outcome→Lesson 账本在，ARC Reflexion 不写入；Lesson 不自动发布 Memory/Skill",
        ),
    ]
    for label, module_name, symbol, note in checks:
        try:
            mod = importlib.import_module(module_name)
            exists = hasattr(mod, symbol)
            rows.append(_ok(f"能力资产: {label}", exists, note, symbol=f"{module_name}.{symbol}"))
        except Exception as exc:
            rows.append(_ok(f"能力资产: {label}", False, f"{note} import 失败: {exc}"))
    return rows


def probe_evidence_window() -> list[dict[str, Any]]:
    print("\n=== 历史窗口预检 ===")
    from hypertrade.arc.evidence import preflight_window

    report = preflight_window(symbol="BTC-USDT-SWAP", timeframe="1H")
    possible = bool(report.get("evidence_possible"))
    return [
        _ok(
            "本机可对真实窗口做证据判定",
            possible,
            json.dumps(report, default=str, ensure_ascii=False),
            report=report,
        )
    ]


def main() -> int:
    all_rows: list[dict[str, Any]] = []
    all_rows.extend(probe_m0_controller())
    all_rows.extend(probe_codegen())
    all_rows.extend(probe_arc_loop_honesty())
    all_rows.extend(probe_two_pipelines())
    all_rows.extend(probe_flags_and_gates())
    all_rows.extend(probe_seven_capabilities())
    all_rows.extend(probe_evidence_window())

    passed = sum(1 for r in all_rows if r["passed"])
    failed = len(all_rows) - passed
    print("\n=== SUMMARY ===")
    print(f"passed={passed} failed={failed} total={len(all_rows)}")
    print("JSON_BEGIN")
    print(json.dumps({"passed": passed, "failed": failed, "rows": all_rows}, ensure_ascii=False, default=str))
    print("JSON_END")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
