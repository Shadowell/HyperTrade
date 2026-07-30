# 38 ARC MCTS 与 MAP-Elites 质量-多样性搜寻引擎技术设计

> 文档性质：组件级技术设计规范与算法实现指南。
> 状态：Approved & Active — 2026-07-30。

## 1. 概述与设计背景

在量化策略搜索领域，传统的单次 Prompt 生成或简单重试极其容易陷入**策略同质化**与**局部最优解**。

**ARC MCTS 搜寻引擎** 结合了 **蒙特卡洛树搜索 (Monte Carlo Tree Search)** 与 **MAP-Elites 质量-多样性 (Quality-Diversity / QD)** 算法。它建立了一棵显式的策略代码演化树 (`MCTSNode` Tree)，采用上限置信区间算法 (UCB1) 选择最具潜力的扩展节点，并在多维特征网格中保留不同风格（如：短/中/长期 x 多种 Regime 适应度）的精英策略代码。

---

## 2. 核心算法与数学公式

### 2.1 UCB1 节点选择公式

节点在演化树上的选择得分计算公式如下：

$$UCB1_i = \bar{V}_i + c \sqrt{\frac{\ln N_{parent}}{N_i}}$$

* $\bar{V}_i$: 节点 $i$ 的平均评估得分（例如，红蓝对抗后的夏普比率与风控得分组合）。
* $N_{parent}$: 父节点的总访问次数。
* $N_i$: 当前节点 $i$ 的访问次数。
* $c$: 探索常数（默认设为 $1.414$ / $\sqrt{2}$），平衡“利用高分策略 (Exploitation)”与“探索未知节点 (Exploration)”。

### 2.2 MAP-Elites 质量-多样性网格

系统维护一个二维特征归档字典：

```text
Archive Key: (Holding_Horizon_Bucket, Regime_Fit_Bucket)
```

1. **Holding Horizon 维度**：根据策略代码中 `lookback_period` 分为 `short_term` (<=10), `medium_term` (10-40), `long_term` (>40)。
2. **Regime Fit 维度**：根据表现分为 `trending_strong`, `ranging_moderate`, `defensive_low_vol`。
3. **精英保留规则**：每次产生新候选节点时，若对应单元格为空，直接入库；若单元格非空，仅当新节点的 $\bar{V}_i$ 优于现有精英时，才更新该单元格。

---

## 3. 代码接口与类设计

组件代码位于 [backend/src/hypertrade/arc/mcts.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/backend/src/hypertrade/arc/mcts.py)：

```python
class MCTSNode(BaseModel):
    node_id: str
    attempt: ARCCandidateAttemptV1
    parent_id: str | None = None
    children_ids: list[str] = Field(default_factory=list)
    visits: int = 0
    total_value: float = 0.0
    depth: int = 0
    feature_descriptor: tuple[str, str]

    def ucb1_score(self, parent_visits: int, exploration_weight: float = 1.414) -> float: ...


class MAPElitesGrid:
    def add_candidate(self, node: MCTSNode) -> bool: ...
    def get_elites(self) -> list[MCTSNode]: ...


class ARCMCTSEngine:
    def select_best_node_to_expand(self) -> MCTSNode | None: ...
    def backpropagate(self, node_id: str, value: float) -> None: ...
```

---

## 4. 单元与集成测试

详见 [tests/test_arc_mcts.py](file:///Users/jie.feng/Dev/Github/Private/HyperTrade/tests/test_arc_mcts.py)：

```bash
python3 -m pytest tests/test_arc_mcts.py -v
```
测试验证了 UCB1 多节点选择、树深扩展、反向传播 (Backpropagation) 以及 MAP-Elites 单元格更新逻辑。
