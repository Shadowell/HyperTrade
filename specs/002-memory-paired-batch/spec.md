# Feature Specification: 多任务记忆配对评测

**Feature Branch**: `codex/memory-paired-batch-r6`
**Created**: 2026-09-22
**Status**: Ready for implementation

## User Scenarios & Testing

### User Story 1 - 冻结可审计任务矩阵 (P1)

研究者提供至少两个有明确 ID 的隔离 AVO 任务及其来源记录。系统在任何模型调用前冻结任务清单、各 pair 身份、相同 Provider/model、预算、研究窗口和验证策略；拒绝重复 ID、漂移、Paper 授权及越界路径。

**Independent Test**: 隔离夹具创建两个任务；篡改清单或改用另一输入时在运行前拒绝。

### User Story 2 - 中断后继续未完成 pair (P1)

批量运行按冻结顺序调用现有 pair runner；每个 pair 使用独立目录与 journal。跨进程重启后已结算臂不重复执行，未完成臂继续受原预算控制，未知副作用沿用单 pair fail-closed 规则。

**Independent Test**: 替身 Provider 运行一个 pair 后跨进程恢复，调用次数等于每臂一次。

### User Story 3 - 从事实账本汇总过程指标 (P1)

研究者查看每臂候选验证成功率、失败分类、实际模型/工具/回测调用量、开发实验重复率及未知项。缺失用量或证据保持 unknown；单任务或单批量不得输出盈利、因果或记忆效果已证实。

**Independent Test**: 替身生成成功/失败/未知结果；删除缓存汇总后重建的结果相同。

## Requirements

- **FR-001**: 批量 manifest MUST 内容寻址并绑定有序且唯一的任务 ID、pair ID、控制与运行时代码身份；任务数为 2 至 50。批次执行 ID 必须先持久化，同一目录恢复稳定；它与任务 ID 必须进入 pair ID 及外部研究命名空间，使完全相同 goal/memory 的重复任务和不同批次互不碰撞。
- **FR-002**: 各任务 MUST 固定同一 Provider/model、预算上限、研究窗口和验证策略；各臂仅长期记忆输入不同，Paper/Live 保持禁用。
- **FR-003**: 每个 pair MUST 复用原有目录和 SQLite journal；批量状态文件仅是可重建投影，不能代替 journal 判定完成。
- **FR-004**: 批量汇总 MUST 区分完成、待运行、成功验证、失败原因、缺失计费/成本/数据快照及开发实验重复分母；零分母率为 null。
- **FR-005**: 结果 MUST 保持 `conclusion=unknown`、`profitability_claim=false`、`causal_claim=false`，不以模型文字作为裁判。
- **FR-006**: 本切片只用隔离测试替身，不启动真实模型、研究、Paper 或 Live；真实样本和预算由总控另行确定。
- **FR-007**: 未指定批次 scope 的既有单 pair 创建接口与 manifest 形状保持兼容；旧运行时哈希不匹配仍按既有规则拒绝静默续跑。
- **FR-008**: AVO 先压缩、后由配对 Provider 注入记忆时，最终实际发送的消息与工具定义 MUST 再经相同 64k `compaction.v1` 上界和脱敏路径；持久化最终请求 manifest/hash 与私有快照。若必要目标、来源或未决事实无法安全容纳，MUST 以 `avo_context_budget_exhausted` 停止且不得调用模型或工具，不扩大额度或仅靠减少记忆条数规避。
- **FR-009**: 最终实际发送的工具 schema MUST 使用 compaction 回执中的脱敏版本，`tools_hash` 与实际 payload 一致；pair runtime 身份 MUST 覆盖 compaction 与私有上下文 journal 实现变更。

## Success Criteria

- **SC-001**: 两个及以上任务在一次创建中得到可核验冻结矩阵，控制漂移和篡改被拒绝。
- **SC-002**: 跨进程恢复不重放已结算臂，批量汇总可以在删除缓存后从 pair journal 重建。
- **SC-003**: 汇总给出分子/分母与未知项，未完成批次不出现伪成功率。
- **SC-004**: 两个同目标、同记忆但不同 task ID 的重复任务，以及不同批次，均产生四个独立 arm mission ID；同一批次重开不改变这些 ID。
- **SC-005**: 构造原请求低于 64k、注入后超过 64k 的隔离反例，验证 0 次实际模型/工具调用、脱敏阻断清单和诚实终态；小上下文的最终发送 hash 可从 journal 回执核对。
- **SC-006**: 工具 schema 中的敏感字段在实际发送前被脱敏且发送 payload 哈希等于 manifest；两个上下文实现文件任一发生变更都会使冻结 runtime digest 变化。

## Assumptions

- 首版只比较 memory-on/off；旧记忆版本第三臂留给后续合同。
- 任务可以有不同目标和标的，但研究窗口及资源控制必须相同；矩阵创建不调用外部服务。
