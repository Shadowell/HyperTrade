# 40 ARC 多 Regime 定量因果归因与 Reflexion 记忆账本技术设计

> 文档性质：组件级技术设计规范与归因反思机制指南。
> 状态：Approved & Active — 2026-07-30。

## 1. 概述与设计背景

当回测或红队攻击失败时，系统不能仅停留在“输出失败日志”或盲目重试。它必须精确回答：**策略究竟是在什么市场 Regime（环境）下、因为什么具体参数/规则导致的崩溃？**

**ARC 定量因果归因与 Reflexion 记忆账本**（`ARCReflexionLedger` 与 `ARCCausalAttributionEngine`）将历史表现拆解到 4 种市场 Regime 下，提取出结构化的**否定性提示约束 (Negative Constraints)** 并写入持久化账本。

---

## 2. 多 Regime 归因与负向约束提取

### 2.1 4 种市场 Regime 划分

1. `bull_trend_high_vol`: 牛市剧烈上涨环境。
2. `bear_trend_low_vol`: 熊市阴跌环境。
3. `ranging_high_vol`: 高波动率宽幅震荡洗盘环境。
4. `ranging_low_vol`: 低波动率窄幅盘整环境。

### 2.2 负向约束 (Negative Constraints) 生成流程

```text
[尝试失败] ──► [RegimePerformanceDecomposition] ──► [提取具体失败属性] ──► [写入 Reflexion 账本]
                                                                                │
                                                                                ▼
[下一轮突变/生成] ◄──────────────────────────────────────────────────── [注入 Negative Constraints Prompt]
```

生成的约束示例：
* `"止损比例 (stop_loss) 必须限制在 10% 以内以防范大回撤"`
* `"禁止在行情 Regime [ranging_high_vol] 下使用宽止损；洗盘损耗过高"`
* `"均线回看周期 (lookback_period) 必须大于 15 以避免频发砍仓"`

---

## 3. 代码接口与类设计

组件代码位于 [backend/src/hypertrade/arc/reflexion.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/backend/src/hypertrade/arc/reflexion.py)：

```python
class RegimeAttributionResult(BaseModel):
    regime_name: str
    sharpe: float
    max_drawdown: float
    passed: bool
    attribution_notes: str


class ARCCausalAttributionEngine:
    def decompose_regime_performance(
        self, attempt: ARCCandidateAttemptV1, metrics: dict[str, Any]
    ) -> list[RegimeAttributionResult]: ...


class ARCReflexionLedger:
    def diagnose_and_record_failure(
        self,
        attempt: ARCCandidateAttemptV1,
        failure_class: str,
        observed_metrics: dict[str, Any],
        raw_reasons: list[str],
    ) -> ARCReflexionEventV1: ...

    def get_all_negative_constraints(self) -> list[str]: ...
```

---

## 4. 单元与集成测试

详见 [tests/test_arc_reflexion.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/tests/test_arc_reflexion.py)：

```bash
python3 -m pytest tests/test_arc_reflexion.py -v
```
测试验证了多 Regime 性能拆解、失败原因诊断与结构化负向约束在记忆缓冲区中的去重检索。
