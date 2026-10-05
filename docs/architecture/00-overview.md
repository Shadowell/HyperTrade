# 00 Architecture Overview / 架构总览

## Start here / 从这里开始

- [33 System Architecture](33-system-architecture.md) 是核心实现快照（已全面刷新至多市场与企业级生产态）。系统性阐述 Mission Runtime、ARC 自主研究循环（AVO）、默认开启的自主进化引擎、BitPro / QuantLab 双目标适配层与企业级安全治理边界。
- [66 QuantLab 适配器、A 股微观结构与平滑换仓](66-quantlab-adapter-a-share-microstructure-and-relay-handover.md) 规定了 A 股现货市场的硬约束机制（T+1 状态机、现货单向多头、涨跌停阻断、万2.5/5bps 印花税）、Co-STEER 到 QuantLab 原生向量化矩阵策略的转译器，以及赛马接力阶段节省换手摩擦超 80% 的持仓净额对冲与切片执行调度器。
- [67 生产级探活、令牌轮换与指挥台设计](67-production-observability-probes-and-token-rotation.md) 规定了容器级分级探活矩阵（`/livez`, `/readyz`, `/healthz`）、适配器心跳检测、零信任动态安全令牌热轮换引擎（`TokenRotationService`，支持无缝宽限期过渡），以及集成 RD-Agent 假设演进树（HET）的前端多目标指挥台。
- [65 RD-Agent 演进与 FinMem 分层认知记忆](65-rd-agent-evolution-and-finmem-layered-memory.md) 规范了基于假设演进树（HET）的策略衍生系谱、Co-STEER 结构化策略代码合成器与 AST 静态安全穿越门禁，以及 FinMem 风格的三层认知记忆（工作记忆、情景记忆、语义记忆）与经验蒸馏算法。
- [64 全自主量化交易 Agent 架构设计](64-autonomous-trading-agent-system-architecture.md) 阐述了统一感知总线、三速决策协同（秒级执行、小时级 Regime 调配、天级慢速复盘）与受控自主实盘边界。
- [62 Pluggable Market Targets](62-pluggable-market-targets.md) 定义自进化核心与交易平台解耦规范（`market_target.v1` 档案与 `market-evolution.v1` MCP 契约）；[63 Evolution Hardening](63-evolution-effectiveness-alerts-and-benchmark.md) 规范效果账本、数据缺口告警与基准相对退化判定。
- [34 Next-Generation Agent Runtime Audit and Target Design](34-next-generation-agent-runtime-audit-and-target-design.md) 记录了证据驱动的差距评估与 canonical Thread/Turn 协议标准。
- [19 Visual Architecture Map](19-hypertrade-architecture-diagram.md) 面向讨论的系统分层与拓扑大图。
- [30 Professional Agent Runtime V2 Roadmap](30-professional-agent-runtime-v2-roadmap.md) / [31 Technical Design](31-professional-agent-runtime-v2-technical-design.md) 记录 Mission、Catalog、Context、Supervisor、Sandbox 的基础合同。

## System boundary / 系统边界

HyperTrade 拥有受治理的 Agent 控制与研究层：Mission 规划、证据/Artifact 引用、提供商/工具治理、审计、报告、自进化与人工复核。
外部交易系统（BitPro 用于加密货币合约，QuantLab 用于股票与权益资产）作为独立的交易平台与数据源，通过稳定的 MCP/API 契约接入。

HyperTrade 不复制交易平台的内部业务逻辑，不直接读取其内部数据库，不承诺收益，严防主网未经授权的违规执行。缺失、陈旧或冲突的证据保持显式未知，绝不静默编造事实。

## Documentation maintenance / 文档维护规则

- **架构变更同步强准则（Mandatory Rule）**：当整体架构有了新的变更（包括新增核心模块、扩展多市场适配层、调整数据/控制流拓扑、演进存储或执行模型等）时，必须及时同步更新所有相关的设计文档（如 `docs/architecture/` 目录下的架构设计文档、`docs/spec.md`、`docs/progress.md`、相关交付合同）以及中英文 `README`（`README.md`、`README.en.md` 等），严禁出现代码与架构演进但设计文档与 README 滞后或失步的情况。
- 产品范围与验收标准：[Product Spec](../spec.md)
- 当前已验证状态与生产证据：[Progress Log](../progress.md)
- 所有交付合同与 Sprint 规划：[Sprint Contracts](../contracts/)
- 运维与部署操作手册：[Runbooks](../runbooks/)
