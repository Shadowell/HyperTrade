# Implementation Plan: 多任务记忆配对评测

**Branch**: `codex/memory-paired-batch-r6` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

## Summary

在 `evals` 中增加薄批量层，复用已有 `create_pair`/`run_pair` 与每任务独立 journal；冻结矩阵，逐 pair 恢复，聚合确定性过程指标。批次先持久化独立执行 ID，再将执行 ID 与任务 ID 作为显式 scope 纳入 pair 内容哈希；旧单 pair 无 scope 的 manifest 形状不变。原 pair 摘要补充开发实验分母。

## Technical Context

Python 3.12、Pydantic/SQLAlchemy、pytest；本地目录 manifest + 每任务 SQLite journal。独立 CLI/库入口，无 API、worker、生产迁移。

## Constitution Check

- 外部事实与控制分离：批量层不读取或写入 BitPro；通过。
- 历史与权限边界：沿用 pair 的 Paper/Live 拒绝；通过。
- 证据先于完成：结果来自 journal，未知不填补；通过。
- 最小可验证切片：仅两个评测文件与隔离测试；通过。

## Project Structure

- `backend/src/hypertrade/evals/memory_ablation.py`: 开发实验分母和可选、冻结的 pair scope。
- `backend/src/hypertrade/evals/memory_ablation.py`: 最终记忆注入后的 `compaction.v1`、脱敏 manifest/hash 与私有快照。
- `backend/src/hypertrade/arc/avo.py`: 仅将最终请求的 `ContextBlocked` 归类为上下文预算不足；正常 AVO 路径不变。
- `backend/src/hypertrade/evals/memory_ablation_batch.py`: 矩阵、恢复、汇总、CLI。
- `tests/test_memory_ablation_batch.py`: 纯替身/临时目录/子进程回归。
- `specs/002-memory-paired-batch/`: 本切片规格与任务。

## Validation

先定向 pytest、Ruff、mypy；独占窗口再运行 `./scripts/check.sh`。提交前 GitNexus detect-changes；不自行 push 或部署。
