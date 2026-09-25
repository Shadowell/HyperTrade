# 011 模拟盘策略变体 A/B 对决与分叉接力任务清单 (Tasks)

## 任务列表

- [ ] **T001: 扩展变体亲子关系与分叉接力类型定义**
  - 文件：`BitPro/frontend/src/pages/liveTrading/types.ts`
  - 内容：定义 `VariantRelation`, `ForkRelayState`, `TwinGroupSummary`, `ParameterDiffItem` 等类型。

- [ ] **T002: 实现参数 Git-Diff 对比表格组件 (`ParameterDiffTable.tsx`)**
  - 文件：`BitPro/frontend/src/pages/liveTrading/ParameterDiffTable.tsx`
  - 内容：对比 base 与 variant 参数对象，高亮差异值，展示调整方向（▲/▼）与调优因果说明。

- [ ] **T003: 实现 ECharts 分叉接力与同窗双曲线组件 (`ForkRelayEquityChart.tsx`)**
  - 文件：`BitPro/frontend/src/pages/liveTrading/ForkRelayEquityChart.tsx`
  - 内容：基于 `echarts-for-react`，支持绘制 Base 蓝线与 Variant 紫线，标出 Fork 分叉点 `markLine` 与 IS/OOS 切分线。

- [ ] **T004: 实现 A/B 深度比对抽屉工作台 (`VariantComparisonDrawer.tsx`)**
  - 文件：`BitPro/frontend/src/pages/liveTrading/VariantComparisonDrawer.tsx`
  - 内容：集成调优假设、`ParameterDiffTable`、`ForkRelayEquityChart`、量化指标矩阵与“一键启动并行模拟盘”按钮。

- [ ] **T005: 实现模拟详情页进化专区面板 (`InstanceEvolutionPanel.tsx`)**
  - 文件：`BitPro/frontend/src/pages/liveTrading/InstanceEvolutionPanel.tsx`
  - 内容：渲染当前模拟盘的 Agent 诊断、变体候选摘要卡片与“展开 A/B 深度比对”触发按钮。

- [ ] **T006: 在模拟详情页 (`InstanceMonitor.tsx`) 挂载胶囊与进化专区**
  - 文件：`BitPro/frontend/src/pages/liveTrading/InstanceMonitor.tsx`
  - 内容：顶部 Header 增加 AI 诊断胶囊标签；在策略参数下方嵌入 `<InstanceEvolutionPanel />`；连接抽屉开关状态。

- [ ] **T007: 实现概览列表孪生卡片组 (`TwinInstanceCard.tsx`) 与 `InstanceDashboard.tsx` 整合**
  - 文件：`BitPro/frontend/src/pages/liveTrading/TwinInstanceCard.tsx`, `InstanceDashboard.tsx`
  - 内容：按母策略分组渲染孪生卡片，显示分叉后超额收益 Alpha，支持独立操作与采纳升级。

- [ ] **T008: 前端构建与代码质量验收**
  - 命令：在 `BitPro/frontend/` 运行 `npm run build`
  - 目标：确保 0 编译错误、0 类型报错，组件交互完整闭环。
