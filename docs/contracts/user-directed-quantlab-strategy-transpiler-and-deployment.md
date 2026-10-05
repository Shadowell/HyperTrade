# User-Directed Contract — QuantLab 策略格式转译器与代码部署闭环 (Spec 028)

> 状态：Active（2026-10-05 激活）
> 
> 激活原因：产品所有者明确要求——按顺序推进系统优化。首要任务（方向一）为打通 HyperTrade 自主合成策略与 QuantLab 运行时原生策略格式的鸿沟，实现 Co-STEER/自愈策略转译、AST 静态审查、回测验证与模拟盘自动部署的完整闭环。
> 
> 依赖规范：[Spec 025 (QuantLab 市场目标适配)](../progress.md#quantlab-市场目标一等公民适配与多资产自愈闭环-spec-025--2026-10-03), [Spec 026 (RD-Agent & Co-STEER 策略代码合成)](../progress.md#co-steer-策略代码合成与-ast-门禁-spec-026-phase-2--2026-10-04)

---

## 1. 目标 (Goal)

HyperTrade 的 Co-STEER 与自愈进化引擎生成符合通用领域脚手架的 `BaseEvolutionStrategy`（三段式：特征工程 `compute_features`、信号生成 `generate_signals`、动态仓位 `position_sizing`），而 QuantLab 生产端运行的是基于矩阵向量化回测与模拟盘撮合的 `*MatrixStrategy` 规范（声明 `META`、`ENTRY_SIGNALS`、`EXIT_SIGNALS`、`EXECUTION_BACKEND = "matrix_native"` 与 `MATRIX_STRATEGY` 实例）。

本切片实现：
1. **QuantLab 策略转译器 (`QuantLabStrategyTranspiler`)**：自动将 `BaseEvolutionStrategy` 代码或结构化策略定义转译并封装为 QuantLab 原生兼容的 `MatrixStrategy` 独立 Python 模块，且自动注入 A 股/美股元数据与信号映射；
2. **ASTGatekeeper 与安全性双重核验**：转译后的代码必须通过 `ASTGatekeeper` 的无前视时序穿越（No-Lookahead Bias）与安全白名单校验，杜绝数据泄漏与非法调用；
3. **QuantLab 目标适配器部署与回测闭环扩展 (`QuantLabTargetAdapter`)**：
   - 强化 `strategy_create`：在创建时支持自动转译与代码指纹 (`code_sha256`) 记录；
   - 强化 `run_backtest`：支持提交转译后源码至 QuantLab `backtest_start_job`，并以指数退避轮询 `backtest_get_job` 获取标准化金融评价指标；
   - 强化 `deploy_strategy`：串联转译、创建、模拟盘供给（`configure_paper`）与启动（`start_paper`）的全自动交付管道；
4. **自愈引擎集成 (`SelfHealingEvolutionEngine`)**：自愈引擎衍生 A 股/股票策略候选时，直接使用转译器生成 QuantLab 格式代码，并联动真实回测与模拟盘部署。

---

## 2. 交付清单 (Deliverables)

1. **转译器模块**：`backend/src/hypertrade/research/quantlab_transpiler.py`
   - `TranspiledQuantLabStrategy` 数据类（代码、元数据、哈希、参数字典）；
   - `QuantLabStrategyTranspiler` 核心转译器实现。
2. **目标适配器增强**：`backend/src/hypertrade/targets/quantlab.py`
   - 接入转译器与代码生成，完善 `strategy_create`、`run_backtest` 轮询与 `deploy_strategy` 闭环。
3. **自愈引擎桥接**：`backend/src/hypertrade/paper/self_healing.py`
   - 在 `heal_quantlab_strategy()` 中绑定转译器，确保自愈输出符合 QuantLab 原生规范。
4. **单元测试与门禁**：`tests/test_quantlab_transpiler_and_deployment.py`
   - 转译语法与结构测试、时序穿越拒绝测试、适配器创建与回测轮询测试、端到端自愈部署测试。

---

## 3. 验收标准 (Acceptance Criteria)

1. **语法与规范兼容性**：转译后的 Python 代码包含合法 `META`、`ENTRY_SIGNALS`、`EXIT_SIGNALS`、`EXECUTION_BACKEND = "matrix_native"` 与 `MATRIX_STRATEGY`，能被 QuantLab 策略引擎成功载入；
2. **时序安全无前视**：转译代码必须 100% 通过 `ASTGatekeeper` 检验，任何带有未来函数（如 `shift(-k)`）的代码坚决拦截；
3. **闭环完整性**：从 `BaseEvolutionStrategy` 源码或参数变异出发，经由转译器、适配器创建与回测，直至模拟盘部署完成，全流程可自动运行并生成不可篡改的 `code_sha256` 证据；
4. **全量门禁保证**：全量通过 `./scripts/check.sh`（Ruff、Mypy、前端构建、全量 Pytest 绿灯）。
