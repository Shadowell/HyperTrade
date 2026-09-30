# 018 技术实现计划 (Implementation Plan)

## 1. 架构总览与模块划分

```
┌────────────────────────────────────────────────────────────────────────┐
│                   OptimizationManager (Service Facade)                  │
└───────┬────────────────────────────┬────────────────────────────┬──────┘
        │                            │                            │
        ▼                            ▼                            ▼
┌──────────────────┐       ┌──────────────────┐         ┌──────────────────┐
│ ParameterSpace & │       │ BacktestMatrix   │         │ RobustnessGuard  │
│ MutationEngine   │       │ Engine           │         │ & Overfitting    │
│ (Grid/Random/LLM)│       │ (Symbols x TFs)  │         │ (WFO & Plateau)  │
└──────────────────┘       └──────────────────┘         └──────────────────┘
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     │
                                     ▼
                   ┌──────────────────────────────────┐
                   │ Persistence (Study & Trials)     │
                   │ + QuantLab / BitPro Exporter     │
                   └──────────────────────────────────┘
```

### 核心新增与修改模块：
1. **`backend/src/hypertrade/research/optimization/space.py`**:
   - `ParameterSpec`, `IntParam`, `FloatParam`, `CategoricalParam`, `ParameterSpace`
   - `ConstraintRule`
   - `extract_parameter_space_from_code(code: str) -> ParameterSpace`
   - 变异器：`GridSampler`, `RandomSampler`, `LlmMutationSampler`
2. **`backend/src/hypertrade/research/optimization/metrics.py`**:
   - 综合量化指标计算器：Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Profit Factor, Turnover, Exposure
3. **`backend/src/hypertrade/research/optimization/matrix.py`**:
   - `BacktestMatrixEngine`:
     - 多周期 K 线切分（IS / OOS）
     - 并行或批量执行候选策略与参数
     - 汇总各维度评估结果
4. **`backend/src/hypertrade/research/optimization/robustness.py`**:
   - `RobustnessEvaluator`:
     - WFO 样本外衰减检验 (`oos_sharpe / is_sharpe`)
     - 参数敏感度邻域扰动测试 (`Parameter Sensitivity / Ridge Test`)
     - 综合稳健度评分算法 (`compute_robustness_score()`)
5. **`backend/src/hypertrade/research/optimization/exporter.py`**:
   - `export_to_quantlab(study, trial) -> dict`
   - `export_to_bitpro(study, trial) -> dict`
6. **`backend/src/hypertrade/db.py`**:
   - 数据库模型：`OptimizationStudy`, `OptimizationTrial`
7. **`backend/src/hypertrade/research/optimization/service.py`**:
   - `OptimizationService`: 协调全流程的生命周期管理，支持异步后台执行与进度轮询
8. **`backend/src/hypertrade/main.py` & `cli.py`**:
   - REST 路由与 CLI 命令实现

---

## 2. 数据库设计

### 表 1: `opt_studies` (`OptimizationStudy`)
- `id`: String(36), PK (前缀 `opt_study_`)
- `strategy_identifier`: String(128)
- `strategy_code`: Text (可选，对于合成策略)
- `objective`: String(64) (如 `sharpe`, `calmar`, `composite_score`)
- `status`: String(32) (`pending`, `running`, `completed`, `failed`)
- `search_method`: String(32) (`grid`, `random`, `llm`)
- `parameter_space_json`: JSON
- `matrix_config_json`: JSON (symbols, timeframes, is_ratio)
- `best_trial_id`: String(36), Nullable
- `best_parameters_json`: JSON, Nullable
- `best_score`: Float, Nullable
- `total_trials`: Integer
- `completed_trials`: Integer
- `error_message`: Text, Nullable
- `created_at`: DateTime(UTC)
- `updated_at`: DateTime(UTC)

### 表 2: `opt_trials` (`OptimizationTrial`)
- `id`: String(36), PK (前缀 `opt_trial_`)
- `study_id`: String(36), FK -> `opt_studies.id`, Index
- `trial_index`: Integer
- `parameters_json`: JSON
- `status`: String(32) (`pending`, `running`, `completed`, `failed`)
- `is_metrics_json`: JSON (收益、夏普、回撤、胜率等)
- `oos_metrics_json`: JSON
- `sensitivity_score`: Float (平坦度得分 0-100)
- `composite_score`: Float (综合稳健度分 0-100)
- `is_promotable`: Boolean
- `error_message`: Text, Nullable
- `created_at`: DateTime(UTC)
- `updated_at`: DateTime(UTC)

---

## 3. 稳健度与防过拟合评分算法公式

$$\text{Composite Score} = 0.35 \times S_{\text{return\_sharpe}} + 0.25 \times S_{\text{drawdown\_calmar}} + 0.20 \times S_{\text{oos\_stability}} + 0.20 \times S_{\text{sensitivity\_flatness}}$$

1. $S_{\text{return\_sharpe}}$:
   - 归一化 Sharpe（若 Sharpe >= 2.5 赋 100 分，<= 0 赋 0 分）
2. $S_{\text{drawdown\_calmar}}$:
   - 最大回撤越小、Calmar 越高，分数越高；若回撤 > 25% 严重惩罚
3. $S_{\text{oos\_stability}}$:
   - 衰减比率 $R_{\text{oos}} = \frac{\text{Sharpe}_{\text{OOS}}}{\max(0.01, \text{Sharpe}_{\text{IS}})}$
   - 若 $R_{\text{oos}} \in [0.8, 1.2]$ 赋满分 100；若 $R_{\text{oos}} < 0.3$ 或负收益，大幅降至 0-20 分（典型的样本内过拟合）
4. $S_{\text{sensitivity\_flatness}}$:
   - 检验邻域 $(\theta \pm \delta)$ 下的平均表现相较中心点 $\theta$ 的保留率；若邻域均值 / 中心点 >= 0.85 赋 100 分；若急剧下降至 < 0.5 赋 0 分（峭壁过拟合）。
