# 39 ARC 红蓝对抗博弈引擎技术设计 (Red-Blue Adversarial Engine)

> 文档性质：组件级技术设计规范与对抗博弈场景指南。
> 状态：Approved & Active — 2026-07-30。

## 1. 概述与设计背景

静态规则过滤无法有效识别策略代码中的逻辑黑洞、过拟合参数或特定极端行情下的尾部风险。

**ARC 红蓝对抗博弈引擎** 引入了博弈论架构：
* **蓝队 (Blue Team Quant / Inventor)**：专注于根据目标与基因技能发掘新的 Alpha 假设并编写策略代码。
* **红队 (Red Team Quant / Falsifier)**：专职“找茬”，针对蓝队提交的代码施加极端压力测试（黑天鹅高波、流动性枯竭、风控参数过宽陷阱）。

策略必须击败红队的针对性攻防攻击，才能获得确定性验证盖章。

---

## 2. 核心架构与攻防流程

```text
┌─────────────────────────┐                 ┌─────────────────────────┐
│ BlueTeamQuant (蓝队)    │                 │ RedTeamQuant (红队)     │
│ 提出 Alpha 假设 & 代码  ├────────────────►│ 评估极端攻防场景与漏洞  │
└─────────────────────────┘                 └────────────┬────────────┘
                                                         │
                                             ┌───────────┴───────────┐
                                             ▼                       ▼
                                       [攻防未通过]             [攻防通过]
                                             │                       │
                                             ▼                       ▼
                                   触发归因反思/AST突变    获得确定性验证与上线许可
```

### 2.1 红队极端攻击场景 (Adversarial Scenarios)

1. **宽止损陷阱攻击 (Wide Stop-Loss Attack)**：当检测到 `stop_loss > 10%` 时，在模拟剧烈震荡洗盘行情下发起触发，判定其会产生严重回撤。
2. **短期回看过拟合攻击 (Lookback Noise Whipsaw Attack)**：当检测到 `lookback_period <= 5` 时，注入微观高频噪点行情，检测策略是否频发砍仓。
3. **流动性枯竭与滑点穿透攻击 (Liquidity Shock Test)**：在流动性陡降 50% 下模拟交易执行表现。

---

## 3. 代码接口与类设计

组件代码位于 [backend/src/hypertrade/arc/adversarial.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/backend/src/hypertrade/arc/adversarial.py)：

```python
class BlueTeamQuant:
    def propose_initial_strategy(self, objective: str, symbol: str) -> ARCCandidateAttemptV1: ...


class RedTeamQuant:
    def evaluate_adversarial_attack(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[bool, dict[str, Any], list[str]]: ...


class ARCAdversarialEngine:
    def run_adversarial_session(
        self, attempt: ARCCandidateAttemptV1
    ) -> tuple[bool, dict[str, Any], list[str]]: ...
```

---

## 4. 单元与集成测试

详见 [tests/test_arc_adversarial.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/tests/test_arc_adversarial.py)：

```bash
python3 -m pytest tests/test_arc_adversarial.py -v
```
测试验证了蓝队策略初始化、红队攻击拦截、以及通过 AST 突变修正参数后成功通过红队审查的全过程。
