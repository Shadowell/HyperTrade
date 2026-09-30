# Spec 019: 实施计划 (Implementation Plan)

## 1. 架构总览 (Architecture Overview)

```
[Paper / Replay / Sandbox Engine]
            │ (Drawdown / Loss Streak Breach)
            ▼
[PaperAnomalyDetector / ARCAdversarialEngine]
            │
            ▼
[ARCCausalAttributionEngine] ──► 4-Regime Performance Decomposition
            │
            ▼
[ARCReflexionLedger] ──────────► Extract Negative Constraints & Append History
            │
            ├──► [ARCGeneticMutator / LlmMutationSampler] ──► Next-Gen Strategy (剪枝错误空间)
            │
            └──► [ReflexionAlertDispatcher] ───────────────► Feishu Interactive Card Webhook
```

---

## 2. 模块划分与文件规划 (File Organization)

1. **`backend/src/hypertrade/arc/reflexion_alert.py`** (新模块):
   - `ReflexionAlertPayload` 数据模型 (Pydantic)
   - `build_feishu_card_payload`: 构建飞书交互式富文本卡片
   - `build_feishu_text_payload`: 构建纯文本降级格式
   - `dispatch_reflexion_alert`: 统一调度与发送（支持自适应重试、错误兜底、超长保护与审计收据）
2. **`backend/src/hypertrade/arc/reflexion.py`** & **`backend/src/hypertrade/bitpro/paper_monitor.py`** (集成增强):
   - 在 `ARCReflexionLedger.diagnose_and_record_failure` 中添加可选告警通知触发
   - 在 `IncrementalEvolutionTrigger.trigger_re_training` 中无缝调用告警派发
3. **`backend/src/hypertrade/research/rsi_evolution.py`** (新模块):
   - `RsiEvolutionEngine`: 实现 RSI 策略从初代构造、震荡市压力注入、因果反思、负向约束提炼、下一代变异重训、飞书卡片推送的端到端演练服务
4. **`backend/src/hypertrade/main.py`** & **`backend/src/hypertrade/cli.py`** (API 与 CLI):
   - REST 路由：`/api/v1/arc/reflexion/...`
   - CLI 命令：`hypertrade reflexion ...`
5. **单元测试与回归测试**:
   - `tests/test_reflexion_alert.py`
   - `tests/test_rsi_evolution.py`

---

## 3. 验收标准 (Acceptance Criteria)
1. 飞书卡片格式完全符合 Feishu Open API 交互卡片规范，包含红标题、双列字段、因果归因、反思教训列表与跳转链接；
2. 在缺失 Webhook 或 Webhook 返回非 0 业务码时，系统静默降级并记录结构化日志，不阻断交易主逻辑；
3. RSI 策略演练闭环能够成功提炼出针对性的负向约束（如 `stop_loss <= 0.05` 与 `oversold_level` 优化），并演化出后代策略；
4. `./scripts/check.sh` 全量通过（Python lint/typecheck/pytest 100% 绿灯）。
