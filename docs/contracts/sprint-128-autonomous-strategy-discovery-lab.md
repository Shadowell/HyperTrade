# Sprint 128 — Autonomous Strategy Discovery Lab

> 状态：Proposed；依赖 Sprint 126 完成，可与 Sprint 127 实现解耦，但共同依赖 Sprint 129 晋级。

## Goal

让 HyperTrade 在 ResearchMandate 内从真实市场现象、未覆盖 regime、现有策略共同失效和已审核研究知识中，
自动提出全新的可证伪 Alpha 假设，冻结 `StrategySpec`，检查新颖性，并生成通过 BitPro `BaseStrategy` 与隔离
沙箱验证的动态 DB 候选。该 Sprint 不要求存在 parent strategy，也不以调参伪装成新策略。

## Dependencies

- Sprint 125–126 提供 reviewed Outcome/Lesson、真实市场/策略时序、成本和执行质量合同。
- 复用 ResearchMandate、Evidence V2、RAG、ContextPack、StrategySpec、dynamic DB strategy 和策略 sandbox。
- Planner/研究角色只能获得 research-read、strategy-generate/validate 所需最小 capability，不获得 paper/live。

## In Scope

- `DiscoveryMandateV1` 定义允许市场、symbols、timeframes、数据源、策略类别、研究预算、禁止特征和探索比例。
- `MarketPhenomenonV1` 记录可观察现象、窗口、统计摘要、regime、来源、新鲜度、替代解释和 unknown。
- `AlphaHypothesisV1` 在查看 locked OOS 前冻结 economic/market rationale、features、entry/exit、risk、expected
  regime、failure conditions、parameter bounds、required data 和 falsification criteria。
- 支持趋势、均值回归、突破、carry/funding、basis、relative strength、volatility/liquidity 和多周期等白名单研究族；
  新研究族需另行审核 schema 与数据权限。
- `StrategyNoveltyReportV1` 比较现有 StrategySpec、特征、信号/持仓摘要、收益相关性、regime 暴露和 code fingerprint。
- 仅当假设或组合暴露具有可解释差异时标记 novel；换名、微调参数或等价逻辑归类为 existing-strategy variant。
- 从冻结 StrategySpec 生成单一 `BaseStrategy` 动态 DB 代码，经过 schema、lint、import、resource、networkless
  sandbox 和 `strategy_validate_code`。
- 生成候选使用 `strategy_create` 的 reviewed contract，不写 BitPro 文件、不改 registry、不重启服务。
- 保存 hypothesis、prompt/template version、candidate digest、失败原因和所有 Evidence refs；不保存 private reasoning。
- 研究队列允许明确的 `rejected`、`duplicate`、`needs_data`、`sandbox_failed` 和 `candidate_ready` 终态。

## Out of Scope

- 读取 locked OOS 后反向修改假设、failure conditions 或经济解释。
- 自动判断候选有效、自动进入 Paper/Live 或分配资金。
- 任意互联网策略代码安装、任意 Python/shell、网络访问或第三方依赖下载。
- 新闻、论文、RAG 或模型文字直接作为交易有效性证据。
- 无界特征挖掘、自动扩大 symbols/timeframes/data sources 或在线强化学习。
- 复制 BitPro 业务逻辑或直连 BitPro 数据库。

## Done Means

1. 在不指定 parent strategy 的 mandate 下，系统能从真实 Evidence 产生完整、可证伪的 AlphaHypothesis。
2. hypothesis 在 locked OOS 结果可见前冻结，后续任何修改产生新 hypothesis version 和新 trial family。
3. 新颖性报告能把换名、参数微调和高相关等价策略归回已有策略变体。
4. novel candidate 明确新的假设、feature/exposure 或 regime coverage，而不是只声称“逻辑不同”。
5. 生成代码实现单一合法 `BaseStrategy`，通过 networkless sandbox 和 BitPro validation。
6. sandbox 拒绝网络、文件系统越界、动态执行、secret、未知 import、无限循环和资源超限。
7. 相同 hypothesis/template/data snapshot/seed 幂等生成同一 candidate fingerprint。
8. 不成立、重复、缺数据和代码失败的假设全部保留，不被成功候选覆盖或删除。
9. 研究角色不能调用 paper/live/order/capital 工具，prompt injection 下仍为零 dispatch。
10. 至少一个真实数据 discovery canary 完成 phenomenon→hypothesis→novelty→candidate_ready，但不宣称盈利。

## Verification

```bash
uv run pytest tests/test_market_phenomena.py -q
uv run pytest tests/test_alpha_hypotheses.py -q
uv run pytest tests/test_strategy_novelty.py -q
uv run pytest tests/test_autonomous_strategy_discovery.py -q
uv run pytest tests/test_strategy_sandbox.py tests/test_agent_tool_policy.py -q
./scripts/check.sh
git diff --check
```

隔离评测必须覆盖 OOS 泄漏、假设后改、换名策略、相关等价、恶意代码、数据缺口、预算耗尽和 prompt injection。
生产 canary 只创建 research candidate，不启动 Paper 或 Live。

## Handoff

Sprint 129 将 Sprint 127 的已有策略候选和本 Sprint 的全新策略候选放入同一 Research Quarantine；新策略不能
因为“新颖”而获得更低门槛。
