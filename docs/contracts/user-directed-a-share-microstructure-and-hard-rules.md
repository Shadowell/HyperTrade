# User-Directed Contract — A 股市场微观结构与硬规则注入 (Spec 029)

> 状态：Active（2026-10-05 激活）
> 
> 激活原因：产品所有者要求按顺序推进系统优化。在完成 QuantLab 策略转译器与代码部署闭环（Spec 028）后，必须解决 A 股特有的市场微观结构约束（T+1、现货禁止裸做空、涨跌停限制、印花税与摩擦滑点），将硬规则同时注入 LLM/Co-STEER Prompt 生成端与 ASTGatekeeper 静态及动态校验端。
> 
> 依赖规范：[Spec 026 (Co-STEER 策略代码合成与 AST 门禁)](../progress.md#co-steer-策略代码合成与-ast-门禁-spec-026-phase-2--2026-10-04), [Spec 028 (QuantLab 策略格式转译器与代码部署闭环)](../progress.md#quantlab-策略格式转译器与代码部署闭环-spec-028--2026-10-05)

---

## 1. 目标 (Goal)

A 股现货市场具有与加密货币和美股显著不同的制度特征与微观结构。若 AI 策略合成或变异引擎未明确这些硬约束，往往会产生带有“盘中买入当天止损 (T+0 幻觉)”、“现货裸开空 (-1 信号)”或“涨跌停假成交”的无效代码。

本切片实现：
1. **A 股微观结构硬规则标准 (`AShareMarketRules`)**：
   - **T+1 交易交收约束**：T 日买入股份仅在 T+1 日起可卖出，同日不可卖出；
   - **现货禁止裸做空 (Long-Only Spot)**：信号空间严格限定为多头 `1` 或空仓观望 `0`，禁止生成做空信号 `-1`；
   - **涨跌停板流动性约束**：主板 10%、创业板/科创板 20%、ST 5%；涨停封死不可买入，跌停封死不可卖出；
   - **交易摩擦成本与税费模型**：印花税（出让单边 0.05%）、过户费（双边 0.01‰）、券商佣金（双边万 2.5，最低 5 元）、标准滑点（1~2 bps）。
2. **LLM/Co-STEER Prompt 硬规则注入器 (`ASharePromptContext`)**：
   - 将上述制度规则转化为结构化约束 Prompt 模板，在策略合成、假设演进与代码自愈提示词中强制注入。
3. **ASTGatekeeper 扩展 (`market="cn"`)**：
   - 静态语法树检查：当策略针对 A 股或 `market="cn"` 时，严格检测并拦截负向信号常量（`-1`）、空头仓位赋值以及裸做空行为。
4. **转译器与运行时动态规则保障 (`QuantLabStrategyTranspiler`)**：
   - 在转译为 QuantLab 矩阵代码时，自动嵌入 A 股单向长仓限制与 T+1 状态机，防止向量化执行时穿透规约。

---

## 2. 交付清单 (Deliverables)

1. **A 股硬规则定义与校验模块**：`backend/src/hypertrade/research/a_share_rules.py`
   - `AShareMarketRules` 常量与配置；
   - `ASharePromptContext` 提示词渲染器；
   - `AShareRuleValidator` 信号与仓位序列合规性核验器。
2. **ASTGatekeeper A 股安全规则扩展**：`backend/src/hypertrade/research/co_steer.py`
   - 支持 `market` 参数（默认或明确为 `"cn"` 时执行 A 股单向多头与现货约束检查）。
3. **策略转译器 A 股微观规则注入**：`backend/src/hypertrade/research/quantlab_transpiler.py`
   - 转译时注入 T+1 检查与现货多头限制保护。
4. **单元测试与门禁**：`tests/test_a_share_microstructure_rules.py`
   - 覆盖 Prompt 渲染、AST 单向限制拦截、动态 T+1 校验、涨跌停与摩擦成本计算。

---

## 3. 验收标准 (Acceptance Criteria)

1. **AST 严格拦截做空**：对于 A 股策略，若代码中尝试输出 `-1` 或做空仓位，`ASTGatekeeper.validate(code, market="cn")` 必定返回 `valid=False` 并明确指出 A 股现货单向限制；
2. **Prompt 规范无遗漏**：生成提示词必须显式包含 T+1、单向买入、涨跌停和 0.05% 印花税说明；
3. **转译器无缝对齐**：转译后的 QuantLab 模块符合 A 股制度规则；
4. **质量门禁 100% 绿灯**：通过 `./scripts/check.sh`（Ruff、Mypy、前端构建与全量测试）。
