# User-Directed Contract — 前端量化指挥台支持 QuantLab 专属看板与 HET 假设演进树 (Spec 031)

> 状态：Active
> 日期：2026-10-05
> 责任人：Antigravity & Codex

## 1. 契约目标与业务背景

随着 HyperTrade 成功接入 QuantLab 目标平台（Spec 028 转译器、Spec 029 A 股硬规则、Spec 030 净额换仓），前端量化指挥台需具备直观的多平台切换与可视化监控能力：
1. **目标平台切换器 (Target Switcher)**：操作员可在 BitPro 与 QuantLab 平台间无缝切换，实时呈现对应市场的微观结构提示（A 股 T+1、现货单向长仓、万 2.5 佣金与 100 股一手）；
2. **QuantLab 专属策略看板 (QuantLab Strategy Workbench)**：可视化展示 QuantLab 原生/转译策略资产组合（如 600519.SH / 000858.SZ）、代码 SHA-256 指纹、`matrix_native` 向量化执行状态与实盘模拟权益，提供一键回测与部署更新；
3. **RD-Agent 假设演进树 (HET) 与净额换仓监视器 (Hypothesis Tree & Relay Netting Monitor)**：
   - 树状层级呈现科学假设由根节点（Root）到变异分支（Branches）的推演血缘；
   - 呈现节点状态（`PROPOSED`, `TESTED`, `PROMOTED`, `PRUNED`）与夏普比率/PnL 相对变化；
   - 动态监控 Spec 030 净额换仓计划：展示换手节约比例（>80%）、预估节省摩擦损耗（¥）、切片执行进度及手动步进控制。

## 2. 接口契约规范

### 2.1 后端 API 路由
- `GET /api/portfolio/targets`：返回可用目标平台清单（`bitpro`, `quantlab`）及当前环境配置；
- `GET /api/portfolio/targets/quantlab/strategies`：查询 QuantLab 策略配置与当前 Session 盯市快照；
- `POST /api/portfolio/targets/quantlab/strategies/{strategy_id}/backtest`：向 QuantLab 提交异步回测并获取指标收据；
- `GET /api/portfolio/relay/handovers`：查询所有持久化的净额平滑换仓计划；
- `POST /api/portfolio/relay/handovers/{plan_id}/step`：推进指定换仓计划的下一执行切片；
- `GET /api/research/hypothesis-tree`：返回 RD-Agent 假设演进树的节点全谱与系谱关系。

### 2.2 前端视图组件
- 在 `frontend/src/components/portfolio/QuantumPortfolioDashboard.tsx` 增加：
  - **平台切换栏 (Platform Target Switcher)**：支持 BitPro 与 QuantLab 快速切换；
  - **QuantLab 策略专属视图 (QuantLab Tab)**：包含策略标的、代码指纹、模拟权益与回测触发；
  - **RD-Agent 演进树与净额换仓视图 (HET & Relay Tab)**：可视化树状结构与净额换仓切片控制器。

## 3. 验收指标

1. 后端新增端点单元测试全通过；
2. 前端组件 TypeScript 类型检查 (`tsc --noEmit`) 0 报错；
3. 前端测试与构建 (`pnpm build`) 顺利完成；
4. 全量通过 `./scripts/check.sh` 质量门禁。
