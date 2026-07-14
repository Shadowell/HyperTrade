# Sprint 99 - Reproducible Experiment Ledger

> 状态：Proposed，依赖 Sprint 96–98。

## Goal

为每次策略实验生成不可变 `ExperimentManifest` 和稳定 fingerprint，使重复实验可去重、
结果差异可解释、BitPro artifacts 可追溯。

## In Scope

- StrategySpec/代码/参数、窗口、成本、模型、prompt、tool、MCP contract 和 commit 版本 manifest。
- canonical fingerprint、execution/retry 记录和 manifest diff。
- BitPro strategy/job/result/artifact refs 与有界 metrics projection。
- 相同 fingerprint 幂等复用和强制重跑审计。
- API/CLI/报告展示 fingerprint 与差异。

## Out of Scope

- 在 HyperTrade 保存完整 K 线、交易明细或 BitPro raw result。
- 将 provider sampling 变成字节级确定性。
- 自动选择“最赚钱”的实验覆盖原记录。
- 大规模参数优化。

## Deliverables

- `ExperimentManifestV1`、canonical serializer 和 fingerprint service。
- manifest/execution/evidence association migration。
- create/get/diff API、CLI 报告块和 BitPro ref verifier。
- 去重、重跑、hash、ref/contract 变化测试。

## Implementation Plan

1. 锁定 manifest 字段、语义/非语义字段和 normalization 规范。
2. 创建 immutable manifest、execution 和 evidence association 表。
3. 实现 canonical JSON、SHA-256 fingerprint 和唯一约束。
4. 在启动 BitPro 回测前查询 fingerprint，避免重复外部任务。
5. 完成后保存 BitPro refs、metrics projection、artifact hash 和实际 usage。
6. 失败重试创建新 execution，保留原失败，不覆盖 manifest。
7. 实现 manifest diff，按策略、数据、成本、模型、prompt、tool、policy 分类。
8. 在研究报告、候选卡、CLI/TUI projection 中显示 fingerprint。
9. 检查 MCP contract/artifact hash；不兼容时拒绝复用。
10. 完成确定性、并发去重、隐私和兼容测试。

## Done Means

- 字段顺序变化不改变 fingerprint，任一语义输入变化都会改变 fingerprint。
- 相同 fingerprint 的并发请求只启动一次 BitPro 实验。
- 操作员能查看两个实验为什么不同。
- 所有实验关联 Task、ResearchJob、StrategySpec、Evidence 和 BitPro refs。
- manifest/report 不含 credential、完整 prompt、private reasoning 或 raw market data。

## Verification

```bash
uv run pytest tests/test_experiment_manifest.py tests/test_experiment_fingerprint.py -q
uv run pytest tests/test_research_orchestrator.py tests/test_bitpro_mcp_adapter.py -q
./scripts/check.sh
```

## Risks / Notes

- fingerprint 规范一旦发布必须版本化；不能静默修改 canonical 算法。
- provider 非确定性通过多 execution 表达，不伪装成完全可重复输出。
- BitPro contract/version 不兼容时必须新建 manifest 或拒绝运行。

## Handoff

- 下一步：Sprint 100 在 immutable manifest 上增加 OOS、walk-forward 和压力验证。
