# User-Directed Contract — RD-Agent 假设演进与 FinMem 分层认知记忆 (Spec 026)

> 状态：Active（2026-10-04 激活）
> 
> 激活原因：产品所有者明确要求——重点抽取 Microsoft `RD-Agent` 的“假设演进树（HET）与 Co-STEER 结构化策略代码自愈机制”以及 `FinMem` 的“工作记忆-情景记忆-语义记忆三层认知记忆与经验蒸馏模型”，落地到 HyperTrade，全面增强 ARC 的自主研究循环与自进化闭环。
> 
> 技术设计基准：[docs/architecture/65-rd-agent-evolution-and-finmem-layered-memory.md](../architecture/65-rd-agent-evolution-and-finmem-layered-memory.md)

---

## 1. 目标 (Goal)

构建生产级自主研究与认知记忆演进中枢，解决 ARC 假设同质化探索、策略代码缺乏编译期 AST 门禁自愈、以及历史经验无法分层沉淀归因的问题：
1. **记忆分层与经验升华**：实现 Working Memory (WM) 即时上下文、Episodic Memory (EM) 情景事件与 Semantic Memory (SM) 通用量化断言三层体系，支持 Regime 敏感的检索惩罚与基于因果归因的异步记忆蒸馏。
2. **结构化假设拓扑**：将策略研究组织为假设演进树（DAG），支持 6 种明确变异类型与向量去重，对同窗基线劣化的分支实现自动化剪枝（Pruning）。
3. **安全且自愈的代码合成**：通过 `BaseEvolutionStrategy` 统一脚手架与 `ASTGatekeeper` 静态审查（防代码注入、防未来函数时序穿越），并在沙箱中实现局部错误自愈重试。

---

## 2. 交付切片规划 (Delivery Slices)

### Slice 1 (Phase 1): 数据契约与分层认知记忆基础设施
* **数据库模型与 DDL**：
  * 在 `hypertrade.db` 中新增 `ArcHypothesisNode`、`ArcEpisodicMemory`、`ArcSemanticAssertion` 实体；
  * 支持 JSONB 元数据与 `pgvector` 嵌入向量存储。
* **分层记忆服务 (`LayeredMemoryService`)**：
  * **Working Memory (WM)**：短期 Turn 上下文生命周期管理、Token 预算控制；
  * **Episodic Memory (EM)**：实验实例与模拟盘退化事件持久化，支持标的、周期、Regime 与向量检索；
  * **Semantic Memory (SM)**：通用因果量化断言存取、置信度维护与状态管理；
  * **Regime 敏感评分检索**：实现 $S(i) = \alpha \cdot \text{CosineSim} + \beta \cdot \text{RegimeMatch} + \gamma \cdot \text{Confidence}$ 打分，对跨 Regime 错配经验施加严重惩罚。
* **单元测试与门禁验证**：新增 `tests/test_layered_cognitive_memory.py`，确保模型映射与检索算法测试 100% 绿灯。

### Slice 2 (Phase 2): Co-STEER 策略代码合成与 AST 门禁
* **领域脚手架 (`BaseEvolutionStrategy`)**：
  * 强制三段式结构：特征工程 `compute_features()`、信号生成 `generate_signals()`、仓位控制 `position_sizing()`。
* **AST 静态安全与时序穿越门禁 (`ASTGatekeeper`)**：
  * 静态 AST 遍历，严禁非白名单导入与危险反射调用；
  * 严格检测对未来的切片（如 `shift(-k), k > 0`）与未来全局统计量泄漏。
* **沙箱局部自愈循环 (Local Self-Healing Loop)**：
  * 在隔离沙箱捕获编译/运行期 Traceback，支持最多 2 次局部自愈修复，不污染外层 Mission 上下文。
* **测试与验证**：新增 `tests/test_co_steer_codegen.py`，覆盖恶意代码拦截、时序穿越识别与自愈修复。

### Slice 3 (Phase 3): 假设演进树 (HET) 与异步蒸馏 Worker
* **假设演进树管理 (`HypothesisTreeService`)**：
  * 树节点创建、变异谱系追踪（6 种变异类型）、语义向量去重；
  * 基于同窗基线指标（相对 PnL、夏普）执行自动化剪枝。
* **异步记忆蒸馏后台 Worker (`MemoryDistillationWorker`)**：
  * 聚类高频情景记忆（频次 $\ge 3$ 或单点重大退化事件）；
  * 调用因果分析模型提炼通用规则，执行冲突检测与旧规则置换（`deprecated`）。
* **ARC 研究循环全链路打通**：
  * 在 `CandidateGenerator` 与自主进化引擎中挂载假设演进树与分层记忆检索。

---

## 3. 验收标准 (Acceptance Criteria)

2026-10-05 审查修复以 [Spec 027](../../specs/027-gemini-review-corrections/spec.md) 为补充合同：宿主禁止执行模型代码；生产认知实体使用 Alembic 0049；持久 ARC 事件接入 HET/episode 与有界召回，最终留出证据不得反向影响模型可见假设树或经验。蒸馏需独立启用，证据/提示词/模型版本相同不得重复付费或生成新断言，仅语义相似不得废弃旧规则。当前嵌入列为 JSON 存储与确定性检索辅助，不宣称已经部署 pgvector 或语义嵌入模型。DSR 的服务端试验族、完整收益统计及 unknown 阻断规范见 Spec 027。

1. **确定性与无偏性**：生成的代码 100% 经受 AST 门禁检验，杜绝代码注入与时序穿越；
2. **记忆隔离与惩罚有效性**：跨 Regime（如牛市追高策略记忆）在熊市/震荡市检索时受到严厉打分惩罚，防止经验误导；
3. **演进拓扑自洽**：假设演进树能清晰展示策略的血缘演进与剪枝原因；
4. **全量质量门禁**：新增功能单测覆盖率 $\ge 90\%$，全量通过 `./scripts/check.sh`（前端测试构建 + 后端 Ruff + Mypy + Pytest 全绿）。
