# Sprint 119 — 生产流终态恢复与实盘策略排名诚实性

> 状态：Closed — 2026-07-16。

## Goal

修复生产 `ht` 在 Mission 已完成后仍只显示“无最终报告”的 P0 交付故障；对“最好的实盘策略”只在 BitPro
返回可比较收益数据时给出排名，否则明确返回数据缺口，绝不按列表顺序猜测。

## In Scope

- `POST /api/agent/runs/stream` 在 Mission 投影异常、Legacy Task 执行异常或控制中断时，始终发送一个不含内部异常的可渲染 `final` 事件。
- 远程 CLI 在 SSE 未收到 `final` 时，使用已收到的 Mission/Run/Task 标识读取持久化终态；恢复失败时显示分类错误和可追踪编号，而不是通用 EOF 文案。
- 实盘策略意图识别覆盖“最好/最佳/最差”；排名、最佳、最差和绩效查询需要每条候选具有可解析的 `return_pct`。
- `OperatorResponseV1.decision` 永远受 600 字符硬上限保护；长证据保留在证据段，不能让终态投影失败。

## Out of Scope

- 主网、模拟盘、Testnet 下单或策略生命周期变更。
- 为缺失的 BitPro 实盘收益字段回填、估算或从策略名称推断绩效。
- 重新设计完整的 token 级回答流或更改外部 BitPro 业务逻辑。

## Done Means

- 同一生产只读请求不再输出 `Run stream ended without final report.`。
- 发生内部投影失败时，SSE 仍含 `final`，且公开帧不含内部错误详情。
- “看下我最好的实盘策略是哪个？”在有完整收益率时返回最高者；缺失收益率时返回 `needs_data`、明确缺口和下一步。
- 受控 100 条评测和新增回归均不能以失去终态、空结论或虚假排名通过。

## Verification

```bash
./scripts/check.sh
HYPERTRADE_EVAL_TARGET=isolated ./scripts/run_operator_task_completion_eval.sh
```

生产只读验收：部署后运行 `ht ask '看下我最好的实盘策略是哪个？'`；确认 API 流含 `final`，CLI 显示最终
报告或明确的收益数据缺口与跟踪编号。

## Handoff

验证完成：生产 `ht ask '看下我最好的实盘策略是哪个？'` 在 Codex Provider 和真实 BitPro 策略
数据上返回受控终态；由于 20 条记录没有可比较的收益字段，最终回答明确说明不能确定最佳/最差策略，
并要求补齐 `return_pct`、`total_pnl` 与统计截止时间。它没有输出旧的 EOF 文案，也没有按列表顺序猜测。

`./scripts/check.sh` 完成：667 tests passed；独立 `hypertrade-eval` 固定任务集完成：100/100、P0=0、P1=0。
这证明本 Sprint 的流终态和受控任务集通过；它不构成盈利能力、自动化交易或所有真实数据源完整性的声明。
