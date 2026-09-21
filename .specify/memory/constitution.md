# HyperTrade Constitution

## Core Principles
### I. 外部事实与内部控制分离
BitPro 拥有行情、回测与 Paper 执行事实；必须经稳定合同读取，不复制交易业务逻辑。
### II. 历史与权限边界
必须保留原 Paper 会话、权益、订单和版本；未知副作用先对账。研究与告警不授予 Live 权限。
### III. 证据先于完成声明
分别记录实现、测试、部署和真实验收；缺失身份、窗口、成本或回执必须保持 unknown。
### IV. 最小可验证切片
先明确需求验收，行为修复先有失败回归；复用持久账本，避免第二套事实源。
### V. 运维可见与隐私
阻塞、投递失败和恢复必须可观察。不得公开密钥、Webhook、私有上下文或未脱敏异常。

## 技术与兼容约束
复用 Python/FastAPI/SQLAlchemy、PostgreSQL 和 React；旧记录保持可读，证据不倒填。

## 开发与验证
遵守 AGENTS.md 的影响分析、完整 scripts/check.sh、逻辑提交与主线部署核验规则。
采用 specify → clarify → plan → tasks → analyze → implement → converge。

## Governance
从现有规则提炼；用户当前指令和 AGENTS.md 优先。原则变更说明版本和适用范围。

**Version**: 1.0.0 | **Ratified**: 2026-09-21 | **Last Amended**: 2026-09-21
