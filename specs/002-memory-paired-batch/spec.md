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

- **FR-001**: 批量 manifest MUST 内容寻址并绑定有序且唯一的任务 ID、pair ID、控制与运行时代码身份；任务数为 2 至 50。
- **FR-002**: 各任务 MUST 固定同一 Provider/model、预算上限、研究窗口和验证策略；各臂仅长期记忆输入不同，Paper/Live 保持禁用。
- **FR-003**: 每个 pair MUST 复用原有目录和 SQLite journal；批量状态文件仅是可重建投影，不能代替 journal 判定完成。
- **FR-004**: 批量汇总 MUST 区分完成、待运行、成功验证、失败原因、缺失计费/成本/数据快照及开发实验重复分母；零分母率为 null。
- **FR-005**: 结果 MUST 保持 `conclusion=unknown`、`profitability_claim=false`、`causal_claim=false`，不以模型文字作为裁判。
- **FR-006**: 本切片只用隔离测试替身，不启动真实模型、研究、Paper 或 Live；真实样本和预算由总控另行确定。

## Success Criteria

- **SC-001**: 两个及以上任务在一次创建中得到可核验冻结矩阵，控制漂移和篡改被拒绝。
- **SC-002**: 跨进程恢复不重放已结算臂，批量汇总可以在删除缓存后从 pair journal 重建。
- **SC-003**: 汇总给出分子/分母与未知项，未完成批次不出现伪成功率。

## Assumptions

- 首版只比较 memory-on/off；旧记忆版本第三臂留给后续合同。
- 任务可以有不同目标和标的，但研究窗口及资源控制必须相同；矩阵创建不调用外部服务。
