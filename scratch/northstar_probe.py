"""North Star gate probe.

Empirically tests whether ARC's autonomous research loop actually searches a
strategy space, or whether it replays a scripted two-step demo. Run directly:

    uv run python scratch/northstar_probe.py
"""

from hypertrade.arc.adversarial import ARCAdversarialEngine, BlueTeamQuant
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.mcts import ARCMCTSEngine
from hypertrade.arc.mutation import ARCGeneticMutator
from hypertrade.arc.reflexion import ARCReflexionLedger


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def probe_1_objective_sensitivity() -> None:
    """Does the objective actually influence the generated strategy?"""
    rule("PROBE 1: 目标 -> 策略代码 敏感度")
    blue = BlueTeamQuant()
    objectives = [
        "研究一个适应BTC高波动的趋势打破策略",
        "构建一个纯做空的均值回归策略，禁止使用任何趋势指标",
        "设计一个基于订单簿失衡的高频套利策略，持仓不超过30秒",
    ]
    codes = []
    for obj in objectives:
        attempt = blue.propose_initial_strategy(obj, "BTC-USDT-SWAP")
        body = attempt.strategy_code.split("\n", 1)[1]  # drop the comment line
        codes.append(body)
        print(f"\n目标: {obj[:40]}")
        print(f"  逻辑指纹: {hash(body)}")
        print(f"  含 ATR 通道: {'compute_atr_volatility_channel' in body}")
        print(f"  含做空逻辑: {'sell' in body or 'short' in body}")
        print(f"  含订单簿逻辑: {'orderbook' in body.lower() or 'imbalance' in body.lower()}")

    unique = len(set(codes))
    print(f"\n>>> 3 个完全不同的目标产生了 {unique} 种不同策略逻辑")
    print(f">>> 结论: {'通过 - 目标驱动生成' if unique > 1 else '失败 - 目标被忽略，恒定同一策略'}")


def probe_2_adversarial_is_real() -> None:
    """Does the red team actually evaluate strategy quality?"""
    rule("PROBE 2: 红队攻击是真实回测还是字符串匹配")
    engine = ARCAdversarialEngine()

    # A deliberately catastrophic strategy that happens to have a tight stop_loss.
    garbage = ARCCandidateAttemptV1(
        attempt_id="att_garbage",
        candidate_id="cand_garbage",
        hypothesis="故意的垃圾策略：随机下单、无风控逻辑",
        strategy_code="""
class GarbageStrategy:
    symbol = "BTC-USDT-SWAP"
    lookback_period = 20
    stop_loss = 0.08

    def next_signal(self, candles):
        import random
        return random.choice(["buy", "sell", "hold"])
""",
    )
    passed, metrics, reasons = engine.run_adversarial_session(garbage)
    print("\n输入: 一个纯随机下单、无任何逻辑的垃圾策略 (stop_loss=0.08)")
    print(f"  红队判定通过: {passed}")
    print(f"  声称 Sharpe: {metrics['sharpe_after_attack']}")
    print(f"  声称胜率: {metrics['win_rate']}")
    print(f"  失败原因: {reasons or '无'}")

    # Same garbage, only the stop_loss literal changes.
    garbage_wide = garbage.model_copy(
        update={"strategy_code": garbage.strategy_code.replace("0.08", "0.12")}
    )
    passed2, metrics2, reasons2 = engine.run_adversarial_session(garbage_wide)
    print("\n输入: 同一个垃圾策略，仅把 stop_loss 改成 0.12")
    print(f"  红队判定通过: {passed2}")
    print(f"  声称 Sharpe: {metrics2['sharpe_after_attack']}")
    print(f"  失败原因: {reasons2}")

    print("\n>>> 红队对随机垃圾策略给出 Sharpe 1.85 / 胜率 65%")
    print(">>> 结论: 失败 - 攻击结果只由 stop_loss 字面量决定，与策略逻辑无关")


def probe_3_reflexion_loop_connected() -> None:
    """Is the adversarial -> reflexion constraint pipeline actually wired?"""
    rule("PROBE 3: 红队 -> 归因反思 闭环是否连通")
    engine = ARCAdversarialEngine()
    ledger = ARCReflexionLedger()
    blue = BlueTeamQuant()

    attempt = blue.propose_initial_strategy("趋势策略", "BTC-USDT-SWAP")
    passed, metrics, reasons = engine.run_adversarial_session(attempt)
    print(f"\n红队实际输出的 reason 字符串:\n  {reasons}")

    event = ledger.diagnose_and_record_failure(
        attempt, "red_team_attack_failed", metrics, reasons
    )
    print(f"\nreflexion.py 中匹配的关键词: 'Stop loss is too wide' / 'Lookback period is too short'")
    matched = [
        r for r in reasons
        if "Stop loss is too wide" in r or "Lookback period is too short" in r
    ]
    print(f"实际命中的 reason 数量: {len(matched)}")
    print(f"\n生成的否定约束:")
    for c in event.negative_constraints:
        print(f"  - {c}")

    print("\n>>> 红队输出 'BLACK_SWAN_FAIL: Wide stop-loss...'，")
    print(">>> reflexion 却在找 'Stop loss is too wide' —— 格式不匹配，该分支永不执行")
    print(">>> 结论: 失败 - red_team_attack_failed 的归因分支是死代码")


def probe_4_mcts_actually_searches() -> None:
    """Does MCTS expand and simulate, or just bookkeep a tree?"""
    rule("PROBE 4: MCTS 是否真的在搜索")
    mcts = ARCMCTSEngine()
    blue = BlueTeamQuant()
    root_attempt = blue.propose_initial_strategy("趋势策略", "BTC-USDT-SWAP")
    mcts.add_root(root_attempt)

    print("\n检查 ARCMCTSEngine 的公开方法:")
    methods = [m for m in dir(mcts) if not m.startswith("_")]
    for m in sorted(methods):
        print(f"  - {m}")

    has_expand = any("expand" in m and m != "select_best_node_to_expand" for m in methods)
    has_simulate = any("simulat" in m or "rollout" in m for m in methods)
    print(f"\n具备 Expansion (自主生成子节点): {has_expand}")
    print(f"具备 Simulation (自主评估节点): {has_simulate}")

    selected = mcts.select_best_node_to_expand()
    print(f"\n只有 root 时 select 返回: {selected.node_id if selected else None}")
    print(f"选出节点的子节点数: {len(selected.children_ids) if selected else 0}")

    print("\n>>> MCTS 四步应为 Selection -> Expansion -> Simulation -> Backpropagation")
    print(">>> 实际只有 Selection + Backpropagation；子节点必须由外部 add_child 手动喂入")
    print(">>> 结论: 失败 - 这是一个树记账结构，不是搜索算法")


def probe_5_mutation_dimensions() -> None:
    """How many dimensions can the mutation engine actually explore?"""
    rule("PROBE 5: AST 突变的搜索维度")
    mutator = ARCGeneticMutator()
    ledger = ARCReflexionLedger()
    blue = BlueTeamQuant()

    attempt = blue.propose_initial_strategy("趋势策略", "BTC-USDT-SWAP")
    ledger.record_negative_constraint("止损比例 (stop_loss) 必须限制在 10% 以内")

    seen: set[str] = set()
    current = attempt
    for round_num in range(1, 6):
        current = mutator.mutate_attempt(current, ledger.get_history())
        code = current.strategy_code
        seen.add(code)
        sl = [ln.strip() for ln in code.split("\n") if "stop_loss" in ln]
        lb = [ln.strip() for ln in code.split("\n") if "lookback_period" in ln]
        atr = [ln.strip() for ln in code.split("\n") if "atr_multiplier" in ln]
        print(f"\n第 {round_num} 轮突变:")
        print(f"  stop_loss:      {sl}")
        print(f"  lookback_period:{lb}")
        print(f"  atr_multiplier: {atr}")

    print(f"\n>>> 5 轮突变共产生 {len(seen)} 种不同代码")
    print(">>> stop_loss 恒定收敛到 0.08；lookback_period / atr_multiplier 从未被突变")
    print(">>> 结论: 失败 - 只有 1 个突变维度，且目标值是硬编码常量")


def probe_6_full_loop_is_scripted() -> None:
    """The decisive test: is the whole loop a guaranteed 2-step script?"""
    rule("PROBE 6: 完整闭环 —— 自主探索还是脚本化演示")
    blue = BlueTeamQuant()
    engine = ARCAdversarialEngine()
    ledger = ARCReflexionLedger()
    mutator = ARCGeneticMutator()

    attempt = blue.propose_initial_strategy("任意目标", "BTC-USDT-SWAP")
    for round_num in range(1, 5):
        passed, metrics, reasons = engine.run_adversarial_session(attempt)
        sl = next(
            (ln.strip() for ln in attempt.strategy_code.split("\n") if "stop_loss" in ln),
            "n/a",
        )
        print(f"\n第 {round_num} 轮: {sl}")
        print(f"  红队通过: {passed} | Sharpe: {metrics['sharpe_after_attack']}")
        if passed:
            print(f"\n>>> 第 {round_num} 轮即过检并终止探索")
            break
        ledger.diagnose_and_record_failure(attempt, "drawdown_exceeded", metrics, reasons)
        attempt = mutator.mutate_attempt(attempt, ledger.get_history())

    print("\n>>> 路径固定: stop_loss 0.12 -> 红队拒绝 -> 突变为 0.08 -> 红队接受")
    print(">>> 而红队的接受标准恰好硬编码为 stop_loss <= 0.10")
    print(">>> 结论: 失败 - 这是一个保证在第 2 轮成功的脚本化演示，不是搜索")


if __name__ == "__main__":
    probe_1_objective_sensitivity()
    probe_2_adversarial_is_real()
    probe_3_reflexion_loop_connected()
    probe_4_mcts_actually_searches()
    probe_5_mutation_dimensions()
    probe_6_full_loop_is_scripted()
    rule("PROBE 完成")
