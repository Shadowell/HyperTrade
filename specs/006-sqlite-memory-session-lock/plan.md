# Implementation Plan: SQLite 内存会话串行化

**Branch**: `codex/memory-paired-batch-r6` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

## Summary

在 `Database` 实例内部对已使用 `StaticPool` 的 SQLite 内存连接建立 `RLock`，只在该实例的 `session()` contextmanager 中覆盖完整事务生命周期。保持其它数据库路径原样。

## Technical Context

Python 3.14 当前测试运行时；SQLAlchemy 2、SQLite StaticPool、pytest。无迁移、无生产数据操作。

## Constitution Check

仅修复隔离数据库连接竞态；不触碰 BitPro/Paper/Live。确定性红测先行，异常和回滚保持原合同。项目 CRITICAL 影响已告警，完整检查由总控执行。

## Project Structure

- `backend/src/hypertrade/db.py`: 单实例内存 session 锁。
- `tests/test_db_session_concurrency.py`: 事务并发、异常释放、非内存边界。
- `specs/006-sqlite-memory-session-lock/`: 本次规格与验证任务。
