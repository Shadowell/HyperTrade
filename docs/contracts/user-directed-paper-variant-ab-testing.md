# Contract: 模拟盘策略变体 A/B 对决与分叉接力系统

## 1. 契约目标
- 本契约规定 BitPro 前端模拟盘页面与 HyperTrade Agent 自主进化系统之间的变体 A/B 对决交互规范。
- 重点解决：
  1. 模拟详情页（`InstanceMonitor`）作为核心入口，嵌入 AI 诊断胶囊与进化专区。
  2. 概览列表（`InstanceDashboard`）采用「孪生家族卡片组」，一目了然关联母子策略并展示分叉超额收益（Alpha）。
  3. 变体启动时继承 Base 策略当前动态总权益，实现数据基础与净值曲线的平滑分叉接力。

## 2. 参与角色
- **总指挥 & 验收人**：Antigravity Agent（统筹、规格制定、任务分解、验收核验）。
- **执行开发**：Codex 6 Sol Medium（按照 `specs/011-paper-variant-ab-testing/tasks.md` 逐项执行前端组件编写与构建）。

## 3. 验收标准
- `npm run build` 在 BitPro 前端无报错通过。
- 模拟详情页展示 Agent 胶囊与进化卡片。
- A/B 深度比对抽屉完整包含参数 Diff、ECharts 分叉双曲线与量化矩阵。
