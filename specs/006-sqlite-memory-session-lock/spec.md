# Feature Specification: SQLite 内存会话串行化

**Feature Branch**: `codex/memory-paired-batch-r6`
**Created**: 2026-09-22
**Status**: Ready for implementation

## User Scenarios & Testing

### User Story 1 - 并发工具共享内存库时事务安全 (P1)

隔离测试可继续并发派发只读工具；当多个工具写入 Agent trace 时，同一个 `Database("sqlite:///:memory:")` 实例不得让两个 session 同时使用其 `StaticPool` 单连接。

**Independent Test**: 使用事件屏障强制首个 session 持有事务，让第二线程尝试进入；首事务未退出前第二个 session 不得进入，退出后正常完成。

### User Story 2 - 异常后可恢复且其他后端不变 (P1)

首个 session 抛错触发 rollback/close 后，等待线程仍能进入；不同 Database 实例不共用锁，文件 SQLite 与 PostgreSQL 不受这个串行化规则影响。

**Independent Test**: 异常分支、双实例和文件 SQLite 的定向测试；不要求真实生产数据库。

## Requirements

- **FR-001**: 仅 `sqlite:///:memory:` 当前已配置 `StaticPool` 的 Database 实例 MUST 建立独立 `RLock`。
- **FR-002**: 锁 MUST 覆盖 session 创建、yield、commit 或 rollback、close 的完整生命周期；异常后必须释放。
- **FR-003**: 非内存 SQLite 与其他数据库 MUST 保持既有 session 行为，不引入全局锁或禁用 Agent 工具并行。
- **FR-004**: 不改变 Paper、Live、策略或持久数据。

## Success Criteria

- **SC-001**: 确定性双线程测试在旧实现失败、修复后通过；第二线程仅在首事务结束后进入。
- **SC-002**: 异常后等待线程正常完成；两个独立内存库实例可并行进入。
- **SC-003**: 定向测试、Ruff、mypy 通过；完整检查交由总控串行执行。

## Assumptions

- SQLite 内存库只用于隔离和测试；生产 PostgreSQL 不应被此锁串行化。
