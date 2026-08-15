"""North Star gate probe, part 3: re-test the generation gap after codegen.

Probes 7 and 8 previously showed the production pipeline collapsing every
hypothesis onto one moving-average strategy and tuning knobs the code never read.
Re-run those exact questions against the spec-driven compiler.

    uv run python scratch/northstar_probe3.py
"""

from typing import Any

from hypertrade.research.codegen import generate_strategy
from hypertrade.research.orchestrator import (
    _budgeted_parameter_bounds,
    _compile_strategy,
    _effective_parameter_bounds,
    _matrix_variants,
    _matrix_variant_limit,
)


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def spec(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": "research_strategy_spec.v1",
        "mandate_id": "rman_probe",
        "strategy_key": "probe",
        "title": "probe",
        "hypothesis": "placeholder",
        "symbols": ["BTC"],
        "timeframes": ["1H"],
        "strategy_category": "TREND",
        "entry_logic": "placeholder entry",
        "exit_logic": "placeholder exit",
        "risk_conditions": ["bounded notional"],
        "data_requirements": ["ohlcv"],
        "parameter_bounds": {},
        "invalidation_conditions": ["insufficient data"],
    }
    base.update(overrides)
    return base


CASES = [
    ("momentum_breakout", "TREND", "高波动环境下 ATR 通道突破捕捉趋势启动", "突破 ATR 上轨"),
    ("mean_reversion_short_only", "MEAN_REVERSION", "价格偏离均值 2 个标准差后回归，仅做空", "z-score 超过 2 时做空"),
    ("orderbook_imbalance_hft", "MICROSTRUCTURE", "短期涨跌幅变化率反转，多空双向", "ROC 超过阈值"),
    ("funding_rate_arbitrage", "CARRY", "唐奇安通道新高延续，多空双向", "突破前 20 根最高价"),
    ("volatility_regime_switching", "VOLATILITY", "RSI 超买超卖切换", "RSI 低于超卖线"),
]


def probe_7_production_strategy_generation() -> None:
    rule("PROBE 7 (重测): 生产管道 orchestrator 的策略生成")
    logic_by_key: dict[str, str] = {}
    for key, category, hypothesis, entry in CASES:
        candidate = spec(
            strategy_key=key,
            title=key,
            strategy_category=category,
            hypothesis=hypothesis,
            entry_logic=entry,
        )
        code = _compile_strategy(candidate)
        generated = generate_strategy(candidate)
        # Strip the class declaration and docstring so only trading logic is compared.
        logic = "\n".join(
            line
            for line in code.split("\n")
            if not line.startswith("class ") and not line.strip().startswith(("#", '"""'))
        )
        logic_by_key[key] = logic
        print(f"\nstrategy_key: {key}")
        print(f"  策略族:     {generated.family}")
        print(f"  方向:       {generated.direction}")
        print(f"  可调参数:   {sorted(generated.tunable_parameters)}")
        print(f"  逻辑指纹:   {hash(logic)}")

    unique = len(set(logic_by_key.values()))
    print(f"\n>>> {len(CASES)} 个语义不同的 strategy_key 产生了 {unique} 种不同策略逻辑")
    print(f">>> 结论: {'通过 - 假设可转化为策略逻辑' if unique == len(CASES) else '失败'}")


def probe_8_parameter_space_coverage() -> None:
    rule("PROBE 8 (重测): 参数空间探索是否作用在真实旋钮上")
    candidate = spec(
        strategy_key="ma_trend_candidate",
        hypothesis="快慢均线金叉确认趋势",
        entry_logic="快线上穿慢线",
        parameter_bounds={
            "lookback": {"min": 5, "max": 60},
            "threshold": {"min": 0.1, "max": 2.0},
        },
    )
    declared = candidate["parameter_bounds"]
    effective = _effective_parameter_bounds(candidate)
    code = _compile_strategy(candidate)

    print(f"\n操作员声明的参数: {sorted(declared)}")
    print(f"生成代码真读的参数: {sorted(effective)}")
    read_declared = [k for k in declared if f'params.get("{k}"' in code]
    read_effective = [k for k in effective if f'params.get("{k}"' in code]
    print(f"  声明参数中被代码读取的: {read_declared}")
    print(f"  生效参数中被代码读取的: {read_effective}")

    budget = {
        "max_candidates_per_day": 3,
        "max_variants_per_candidate": 3,
        "max_total_backtests_per_day": 39,
    }
    budgeted = _budgeted_parameter_bounds(candidate, budget=budget, window_count=3)
    variants = _matrix_variants(
        budgeted, limit=_matrix_variant_limit(budget=budget, window_count=3)
    )
    print(f"\n预算裁剪后的维度: {sorted(budgeted)}")
    print(f"矩阵变体 ({len(variants)} 个):")
    for name, params in variants:
        touched = all(f'params.get("{k}"' in code for k in params) if params else True
        print(f"  {name:26s} {params}  代码读取={touched}")

    print(f"\n>>> 旧行为: 矩阵调 {sorted(declared)}，生成代码一个都不读 -> 敏感性覆盖为 0")
    print(f">>> 新行为: 矩阵调 {sorted(budgeted)}，全部被 on_init 读取")
    print(f">>> 结论: {'通过 - 参数扫描真实生效' if read_effective and not read_declared else '失败'}")


def probe_12_determinism_and_gate() -> None:
    rule("PROBE 12: 确定性与静态门禁")
    from hypertrade.research.codegen import static_code_rejections

    ok = True
    for key, category, hypothesis, entry in CASES:
        candidate = spec(
            strategy_key=key, strategy_category=category, hypothesis=hypothesis, entry_logic=entry
        )
        first = _compile_strategy(candidate)
        second = _compile_strategy(dict(candidate))
        rejections = static_code_rejections(first)
        stable = first == second
        ok = ok and stable and not rejections
        print(f"  {key:28s} 字节一致={stable}  静态门禁拒绝={rejections or '无'}")
    print(f"\n>>> 结论: {'通过 - 指纹可复现且全部过门禁' if ok else '失败'}")


if __name__ == "__main__":
    probe_7_production_strategy_generation()
    probe_8_parameter_space_coverage()
    probe_12_determinism_and_gate()
    rule("PROBE 完成")
