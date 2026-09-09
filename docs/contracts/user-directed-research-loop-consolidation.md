# 统一研究闭环实施合同

状态：Active，2026-09-09。产品所有者已批准架构 61 与双入口统一方案，并授权直接删除无用实现。

## 目标

以同一个策略研究生命周期服务支撑独立 CLI 和 BitPro 控制台，保留逐版本 Paper 人审、原策略连续运行、AVO 研究与运行反馈。

## 切片 1：删除孤立实验实现（已验证并部署）

- 删除 ARC portfolio、canary_vault、microstructure、vector_screening 四个无运行调用的实验模块和专属测试。
- 删除仅作为历史诊断、依赖已退役实验的 scratch/northstar_gap_probe.py。
- 保留禁止 live_allowed=True 的合同测试及现有研究、实盘权限和回执校验。
- 历史架构文档标记退役，不清除策略、数据库、Paper 或运行历史。

## 完成标准

没有活动运行代码/脚本引用删除模块；完整 scripts/check.sh 通过；提交、推送并核对部署。
GitNexus 索引未覆盖 ARC 时保留 UNKNOWN 判断，以当前全库静态扫描与测试补充，不能宣称零影响已由图谱证明。

## 范围外

本切片不删除仍被调用的 Kernel、Graph、MCTS、真实风控和本地 Paper；后续先迁移再删除。

## 后续切片

1. 恢复研究服务和数据库依赖，不重置数据。
2. 唯一任务/进度/Paper 审批协议，CLI 与 BitPro 同步接入。
3. 有预算的 AVO 研究反馈、独立验证与可恢复执行。
4. Paper 7+7 衰减检测、参数再回测、再次审批、新旧并行。

以架构 61 的门禁和原策略保护为准；后续切片逐项补充具体实现验收，不以本切片完成替代整个闭环完成。

## 当前切片 2：统一 CLI / BitPro 的 Paper 审核

- 新建 ARC 任务强制逐版本 Paper review，旧预授权参数不能绕过；历史任务可解码与查询。
- GET paper-review 与 POST paper-review/decide 共用候选代码、spec、回测/验证引用、条件和 Paper 配置哈希。
- 认证人类身份审核，签名绑定 paper 动作及 package hash；服务令牌不能批准。
- 状态领取在现有持久层串行，重复决定不重复外部操作，未知回执保留 effect_unknown，禁止盲重试。
- CLI research start/list/status/evidence/candidate/review/continue/decide 调用相同服务；BitPro 页面签名代理相同协议。
- 新协议 Paper 观察不再自动进入 Live 审批，原实例不被此次功能修改；NaN/Infinity/布尔指标不能作数值门禁依据。

验收：完整检查；候选通过后仍零 Paper 写；拒绝、篡改、过期签名、重复/并发领取及事件恢复回归；两端展示同一真实历史任务。
真实候选的人工批准不由验收脚本替用户执行。持久研究领取、AVO、独立样本外协议与 7+7 自动反馈仍按后续切片实现。
