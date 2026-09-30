# 011 模拟盘策略变体 A/B 对决与分叉接力实现计划 (Implementation Plan)

## 1. 架构与文件结构

本次实现主要涉及 BitPro 前端工程及与 HyperTrade 契约适配：
前端仓库：`/Users/jie.feng/Dev/Github/Private/BitPro/frontend/`

```text
frontend/src/
├── pages/liveTrading/
│   ├── InstanceDashboard.tsx             # 增强: 孪生家族卡片组渲染与筛选
│   ├── InstanceMonitor.tsx               # 增强: 顶部胶囊标签与挂载进化专区
│   ├── TwinInstanceCard.tsx              # 新建: 孪生聚合卡片子组件
│   ├── InstanceEvolutionPanel.tsx        # 新建: 详情页中 AI 进化与变体摘要面板
│   ├── VariantComparisonDrawer.tsx       # 新建: A/B 深度比对抽屉工作台
│   ├── ParameterDiffTable.tsx            # 新建: 参数 Git-Diff 对比表格
│   ├── ForkRelayEquityChart.tsx          # 新建: ECharts 分叉接力与同窗双曲线
│   └── types.ts                          # 增强: 变体亲子关系与分叉接力类型定义
```

---

## 2. 核心技术选型与复用

1. **图表绘制**：复用 BitPro 现有的 `echarts-for-react` 与 `echarts` 5.4+，配置双 `line` 系列与 `markLine` 分叉锚点。
2. **动效与过渡**：使用 `clsx` + TailwindCSS 动画（渐变光效、过渡展开）。
3. **接口解耦**：
   - 变体元数据通过 BitPro 现有 `/arc/evolution` 和 `/arc/missions/{id}` 接口读取。
   - 分叉接力创建通过 BitPro 现有 `paper_configure_reviewed` / `paperApi` 接口，传入 `fork_source_id` 与 `initial_equity`。

---

## 3. 开发阶段拆解

- **Phase 1: 数据类型与模型扩展 (`types.ts`)**
  - 定义 `VariantInfo`, `ForkRelayInfo`, `StrategyTwinGroup`。
- **Phase 2: 核心比对与图表组件开发**
  - `ParameterDiffTable.tsx`（高亮 Diff）
  - `ForkRelayEquityChart.tsx`（ECharts 分叉双曲线）
  - `VariantComparisonDrawer.tsx`（抽屉容器）
- **Phase 3: 模拟详情页集成 (`InstanceMonitor.tsx`)**
  - 顶部 Header 状态胶囊
  - `<InstanceEvolutionPanel />` 嵌入正文
- **Phase 4: 概览列表孪生卡片组改造 (`InstanceDashboard.tsx`)**
  - 分组算法与 `<TwinInstanceCard />` 渲染
- **Phase 5: 统筹核验与端到端质检**
  - 运行 `npm run build` 和 `npm run lint` 验证无类型与样式错误。
