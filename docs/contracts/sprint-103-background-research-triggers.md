# Sprint 103 - Background Research Triggers

> 状态：Proposed，依赖 Sprint 96、98、101–102。

## Goal

建立持久、可停用、可去重、受配额约束的后台研究触发器，根据时间、市场状态、策略漂移、
数据异常或评测回归创建 bounded Agent Task。

## In Scope

- schedule、regime change、strategy drift、data quality、evaluation regression trigger。
- PostgreSQL trigger/fire 表、lease、cooldown、quota、dedupe 和 kill switch。
- worker `research_trigger_loop` 和 Task creation adapter。
- trigger API/CLI/TUI 管理与审计。
- evaluation deployment 默认关闭，生产默认 feature-flag 关闭。

## Out of Scope

- trigger 直接调用 BitPro、paper、testnet、live 或 approval API。
- 自动模拟盘/实盘晋升、自动风险预算调整。
- 无限制 cron、任意用户代码条件和外部 webhook execution。
- 重新实现 Monitor/WorldState/Paper Snapshot。

## Deliverables

- trigger schemas/models/service/worker/API/CLI/TUI projections。
- event fingerprint、quota/cooldown/dedupe、global/trigger kill switch。
- existing MonitorRun/WorldState/Paper/Eval adapters。
- concurrency、restart、storm 和 safety tests。

## Implementation Plan

1. 定义 trigger type、condition schema、task budget、quota 和审计字段。
2. 添加 trigger/fire 表、next_run、lease、fingerprint 唯一约束和 migration。
3. 实现 interval/cron next-run 计算和 UTC/DST 规则。
4. 实现 monitor/world-state/paper/eval event adapter，只读取已提交记录。
5. 实现 fingerprint + time bucket 去重、cooldown、daily/global quota。
6. worker 领取 due triggers，事务创建 TriggerFire 和 bounded Task。
7. 所有 trigger 创建任务前重新验证 mandate active、budget 和 feature flag。
8. 增加 API/CLI/TUI enable/disable/run-now/history/kill switch surface。
9. 生产/eval 配置默认关闭，增加 deploy config assertions。
10. 完成多 worker、重启、风暴、禁用和安全路径测试。

## Done Means

- 两个 worker 不会为同一事件创建重复 Task。
- 重启后 next_run、cooldown、quota 和 fire history 保持正确。
- trigger disable/global kill switch 阻止新任务且不删除历史。
- 触发器只能创建 bounded Task，代码路径无法直接到达 write-like adapter。
- 所有后台 Task 在 API/TUI 中可见、可暂停、可取消和可审计。

## Verification

```bash
uv run pytest tests/test_research_triggers.py tests/test_trigger_worker.py -q
uv run pytest tests/test_deployment_config.py tests/test_eval_deployment_config.py -q
./scripts/check.sh
```

## Risks / Notes

- Trigger storm 必须在 Task 创建前去重，不能依赖下游预算兜底。
- cron 时区统一 UTC；显示层转换本地时间，避免 DST 重复执行。
- eval runtime 和未配置 mandate 的环境保持 disabled。

## Handoff

- 下一步：Sprint 104 为长期自动运行增加 Memory/Skill 写入治理。
