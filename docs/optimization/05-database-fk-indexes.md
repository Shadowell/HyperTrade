# 优化计划 5：数据库 ForeignKey + 复合索引

## 现状诊断

`backend/src/hypertrade/db.py` 的 18 个 ORM 模型：
- **零 `ForeignKey`**：`TraceEvent.run_id`、`RagChunk.document_id`、`PaperPosition.session_id` 等关联字段都是纯 `String`，无引用完整性约束
- **零 `relationship()`**：ORM 层面没有对象导航，查询需要手动 JOIN
- **零复合索引**：`(run_id, tool_name)`、`(session_id, status)` 等高频查询组合没有覆盖
- **JSON 列无 GIN 索引**：`MonitorAlertEvent.metric_json` 无法高效做 JSON 路径查询
- **向量存储是 JSON**：`RagChunk.embedding_json` 存为 JSON 列表，不是 pgvector 原生类型

## 目标

渐进式改造，保留 SQLite 兼容性（测试用），启用 PostgreSQL 专有优化（生产用）：

1. 添加 `ForeignKey` + `relationship()` 实现引用完整性
2. 添加复合 `Index` 覆盖高频查询路径
3. 可选：`RagChunk.embedding` 改用 `PGVector` 原生类型（拆为独立 PR）

## 涉及文件

| 操作 | 文件 |
|------|------|
| 改造 | `backend/src/hypertrade/db.py` |
| 新建 | `backend/alembic/versions/0008_add_foreign_keys_and_indexes.py` |
| 改造 | `tests/test_alembic_revisions.py` |

---

## 详细改动

### 1. FK 关系映射

对以下模型添加 `ForeignKey` 约束和对应的 `relationship()`：

```
TraceEvent.run_id       → FK("agent_runs.id", ondelete="CASCADE")
RagChunk.document_id    → FK("rag_documents.id", ondelete="CASCADE")
PaperPosition.session_id → FK("paper_sessions.id", ondelete="CASCADE")
PaperOrder.session_id   → FK("paper_sessions.id", ondelete="CASCADE")
PaperFill.order_id      → FK("paper_orders.id", ondelete="CASCADE")
PaperFill.session_id    → FK("paper_sessions.id")
PaperEvent.session_id   → FK("paper_sessions.id")
BacktestRun.research_id → FK("strategy_research.id")
MonitorRun.monitor_id   → FK("monitor_definitions.id")
MonitorAlertEvent.monitor_id → FK("monitor_definitions.id")
MonitorAlertEvent.run_id → FK("monitor_runs.id")
LiveOrderIntent.source_run_id → FK("agent_runs.id")
StrategyExperiment.research_id → FK("strategy_research.id")
StrategyExperiment.backtest_id → FK("backtest_runs.id")
BitProPaperMonitorSnapshot.previous_snapshot_id → FK("bitpro_paper_monitor_snapshots.id")
```

### 2. 复合索引

新增以下复合索引，覆盖高频查询场景：

| 表 | 新增 Index | 覆盖查询 |
|---|---|---|
| `trace_events` | `(run_id, tool_name)` | 按 run 查看特定工具调用 |
| `trace_events` | `(run_id, status)` | 按 run 筛选失败/完成的事件 |
| `paper_orders` | `(session_id, status)` | 某个 session 的活跃/已成交订单 |
| `paper_positions` | `(session_id, status)` | 当前持仓查询 |
| `paper_fills` | `(order_id, session_id)` | 成交按订单+session 查询 |
| `paper_events` | `(session_id, kind)` | 按 session + 事件类型过滤 |
| `market_tickers` | `(inst_type, change_utc0_pct)` | 涨跌幅排行（含排序） |
| `memory_items` | `(kind, disabled, importance)` | 活跃 memory 按类型和优先级过滤 |
| `memory_items` | `(kind, disabled)` | 活跃 memory 按类型过滤 |
| `monitor_alert_events` | `(monitor_id, level, status)` | 按监控项+级别筛选告警 |
| `monitor_runs` | `(monitor_id, status)` | 查看某个监控的最新运行 |
| `backtest_runs` | `(research_id, strategy_key)` | 策略回测历史 |
| `live_order_intents` | `(environment, status)` | 活跃实盘意向 |
| `jobs` | `(kind, status)` | 后台任务调度查询 |
| `agent_runs` | `(status)` | 运行态查询 |

### 3. 单列索引

以下快速查找字段加单列索引：

| 表 | 单列 Index |
|---|---|
| `agent_runs` | `(created_at)` — 按时间倒序查询 |
| `memory_items` | `(last_used_at)` — LRU 淘汰查询 |
| `rag_chunks` | `(source_path)` — 按来源路径查找 |
| `monitor_definitions` | `(enabled)` — 启用的监控项 |
| `strategy_research` | `(strategy_key)` — 按策略 key 查询 |

---

## 代码示例

### db.py 改造后

```python
from sqlalchemy import ForeignKey, Index, String, Numeric, JSON

class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("run"))
    prompt: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="running")
    report_markdown: Mapped[str | None] = mapped_column(nullable=True)
    report_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_state_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(nullable=True)

    # Relationships
    trace_events: Mapped[list["TraceEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    live_order_intents: Mapped[list["LiveOrderIntent"]] = relationship(
        back_populates="source_run", foreign_keys="LiveOrderIntent.source_run_id"
    )


class TraceEvent(Base, TimestampMixin):
    __tablename__ = "trace_events"
    __table_args__ = (
        Index("ix_trace_events_run_tool", "run_id", "tool_name"),
        Index("ix_trace_events_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("trev"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_name: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="pending")
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    run: Mapped["AgentRun"] = relationship(back_populates="trace_events")


class PaperSession(Base, TimestampMixin):
    __tablename__ = "paper_sessions"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("pses"))
    name: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="active")
    cash: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    equity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)

    positions: Mapped[list["PaperPosition"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    orders: Mapped[list["PaperOrder"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    fills: Mapped[list["PaperFill"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    events: Mapped[list["PaperEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class PaperPosition(Base, TimestampMixin):
    __tablename__ = "paper_positions"
    __table_args__ = (
        Index("ix_paper_positions_session_status", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("ppos"))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="CASCADE"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(nullable=False)
    side: Mapped[str] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    notional: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    status: Mapped[str] = mapped_column(default="open")

    session: Mapped["PaperSession"] = relationship(back_populates="positions")


class PaperOrder(Base, TimestampMixin):
    __tablename__ = "paper_orders"
    __table_args__ = (
        Index("ix_paper_orders_session_status", "session_id", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("pord"))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="CASCADE"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(nullable=False)
    side: Mapped[str] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    target_notional: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    status: Mapped[str] = mapped_column(default="pending")
    reason: Mapped[str | None] = mapped_column(nullable=True)

    session: Mapped["PaperSession"] = relationship(back_populates="orders")
    fills: Mapped[list["PaperFill"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class PaperFill(Base, TimestampMixin):
    __tablename__ = "paper_fills"
    __table_args__ = (
        Index("ix_paper_fills_order_session", "order_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("pfil"))
    order_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id"), nullable=False
    )
    inst_id: Mapped[str] = mapped_column(nullable=False)
    side: Mapped[str] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=0)
    slippage_bps: Mapped[int] = mapped_column(default=0)
    source_ticker_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    order: Mapped["PaperOrder"] = relationship(back_populates="fills")
    session: Mapped["PaperSession"] = relationship(back_populates="fills")


class MemoryItem(Base, TimestampMixin):
    __tablename__ = "memory_items"
    __table_args__ = (
        Index("ix_memory_kind_disabled_importance", "kind", "disabled", "importance"),
        Index("ix_memory_kind_disabled", "kind", "disabled"),
        Index("ix_memory_last_used", "last_used_at"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("mem"))
    kind: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(nullable=True)
    source_tool: Mapped[str | None] = mapped_column(nullable=True)
    disabled: Mapped[bool] = mapped_column(default=False)
    importance: Mapped[float] = mapped_column(default=0.5)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(default=0.5)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    usage_count: Mapped[int] = mapped_column(default=0)


class MarketTicker(Base, TimestampMixin):
    __tablename__ = "market_tickers"
    __table_args__ = (
        Index("ix_market_tickers_type_change", "inst_type", "change_utc0_pct"),
    )

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("mtick"))
    inst_id: Mapped[str] = mapped_column(unique=True, nullable=False)
    inst_type: Mapped[str] = mapped_column(default="SWAP")
    last: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    volume_ccy_24h: Mapped[Decimal | None] = mapped_column(Numeric(36, 18), nullable=True)
    change_utc0_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
```

---

## Alembic 迁移

### 生成迁移

```bash
cd backend
alembic revision --autogenerate -m "add_foreign_keys_and_indexes"
```

### 验证生成的迁移文件

确认 autogenerate 只产生以下类型的变更，无意外 DDL：
- `op.create_foreign_key(...)`
- `op.create_index(...)`
- 无 `op.alter_column` / `op.drop_column` / 表重命名

### 迁移文件示例

```python
# backend/alembic/versions/0008_add_foreign_keys_and_indexes.py

"""add foreign keys and composite indexes

Revision ID: xxxx
Revises: 0007_monitoring_alerts
Create Date: 2026-07-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Foreign Keys
    op.create_foreign_key(
        "fk_trace_events_run", "trace_events", "agent_runs",
        ["run_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_rag_chunks_document", "rag_chunks", "rag_documents",
        ["document_id"], ["id"], ondelete="CASCADE"
    )
    # ... 其余 FK ...

    # Composite Indexes
    op.create_index("ix_trace_events_run_tool", "trace_events", ["run_id", "tool_name"])
    op.create_index("ix_trace_events_run_status", "trace_events", ["run_id", "status"])
    op.create_index("ix_paper_positions_session_status", "paper_positions", ["session_id", "status"])
    op.create_index("ix_paper_orders_session_status", "paper_orders", ["session_id", "status"])
    op.create_index("ix_paper_fills_order_session", "paper_fills", ["order_id", "session_id"])
    op.create_index("ix_market_tickers_type_change", "market_tickers", ["inst_type", "change_utc0_pct"])
    op.create_index("ix_memory_kind_disabled_importance", "memory_items", ["kind", "disabled", "importance"])
    op.create_index("ix_memory_kind_disabled", "memory_items", ["kind", "disabled"])
    op.create_index("ix_monitor_alerts_monitor_level", "monitor_alert_events", ["monitor_id", "level", "status"])
    op.create_index("ix_backtest_runs_research_strategy", "backtest_runs", ["research_id", "strategy_key"])
    op.create_index("ix_live_order_intents_env_status", "live_order_intents", ["environment", "status"])
    op.create_index("ix_jobs_kind_status", "jobs", ["kind", "status"])

    # Single-column Indexes
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_created", "agent_runs", ["created_at"])
    op.create_index("ix_memory_last_used", "memory_items", ["last_used_at"])
    op.create_index("ix_rag_chunks_source_path", "rag_chunks", ["source_path"])
    op.create_index("ix_monitor_definitions_enabled", "monitor_definitions", ["enabled"])
    op.create_index("ix_strategy_research_key", "strategy_research", ["strategy_key"])


def downgrade() -> None:
    # Reverse: drop indexes first, then FKs
    op.drop_index("ix_trace_events_run_tool", table_name="trace_events")
    op.drop_index("ix_trace_events_run_status", table_name="trace_events")
    # ... 其余 drop ...
    
    op.drop_constraint("fk_trace_events_run", "trace_events", type_="foreignkey")
    op.drop_constraint("fk_rag_chunks_document", "rag_chunks", type_="foreignkey")
    # ... 其余 drop FK ...
```

---

## 可选：RagChunk 改用 PGVector

拆为独立 PR `0009_rag_pgvector`：

```python
from pgvector.sqlalchemy import PGVector

class RagChunk(Base, TimestampMixin):
    __tablename__ = "rag_chunks"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: new_id("rchk"))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False
    )
    # 新增：PGVector 原生列
    embedding: Mapped[list[float] | None] = mapped_column(
        PGVector(1024), nullable=True
    )
    # 保留 embedding_json 用于回退 / SQLite 兼容
    embedding_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    document: Mapped["RagDocument"] = relationship(back_populates="chunks")
```

PGVector 需要 `pgvector` Python 包和 PostgreSQL 扩展 `CREATE EXTENSION vector;`。

---

## 实施步骤

1. 在 `db.py` 中给所有模型添加 `ForeignKey` 和 `__table_args__` 中的 `Index` 定义
2. 添加对应的 `relationship()` 到 parent 模型
3. 生成 Alembic 迁移：`alembic revision --autogenerate -m "add_foreign_keys_and_indexes"`
4. 人工审核 autogenerate 产物，确保无意外 DDL
5. 运行 `alembic upgrade head` 验证迁移成功
6. 更新 `tests/test_alembic_revisions.py` 适配新迁移

---

## 验收标准

1. 所有 18 个模型的关联字段有 `ForeignKey`（通过 inspect 或 autogenerate diff 验证）
2. 全部高频查询组合有复合 `Index`
3. `alembic upgrade head` 成功（SQLite 和 PostgreSQL 均可执行）
4. `test_alembic_revisions.py` 通过
5. 所有 254 个测试通过
6. `./scripts/check.sh` 通过

## 面试可讲点

- **引用完整性**：FK 保证数据一致性，`ondelete=CASCADE` 保证联动删除。声明式约束优于应用层检查
- **复合索引 vs 单列索引**：`(run_id, tool_name)` 可以服务 `WHERE run_id = ?` 和 `WHERE run_id = ? AND tool_name = ?` 两种查询 —— 最左前缀原则
- **B-tree 索引选择**：金融数据以等值查询 + 范围排序为主，B-tree 是最优通用选择
- **GIN 索引**（未来）：JSONB 查询加速（`@>`、`?`、`?|` 操作符），`jsonb_path_ops` 比默认 GIN 更小更快
- **为什么之前没有 FK**：SQLite 原型阶段不需要。这是典型的"原型 → 生产"迁移路径，面试官喜欢听到"我知道什么时候该加，什么时候不该加"
- **Alembic migration 安全**：autogenerate + 人工审核，不盲信工具。online migration 检查锁表风险
