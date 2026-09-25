# 012 AI 研发工作台 (/ai-lab) 空间重构与降维设计规格

## 1. 业务目标与背景

当前 BitPro 的 `/ai-lab`（AI 研发工作台）界面存在**双重焦点冲突与信息过度堆叠**的问题：
- 顶部强行堆叠了巨大的全局 `EvolutionPanel`（包含全局开关、调度设置、多行统计瓦片、12 个策略的庞大诊断折叠表格），占据了 500px+ 的垂直空间；
- 底部又堆叠了“左侧 290px 任务列表 + 右侧工作台”的双栏结构；
- 研究来源（ARC、Optimizer、Auto-Agent、投研工作台）被隐蔽在左侧边栏底部的折叠菜单里；
- 导致交易员在进入 `/ai-lab` 时视觉极其杂乱，无法聚焦在特定研发或进化监控任务上。

本规格旨在对 `/ai-lab` 进行**顶层语义分 Tab 解耦**与**金融级清爽布局重构**：
1. **顶层语义三段式 Tab 导航**：
   - **Tab 1: 策略自主进化大盘 (`evolution`)**：全宽大盘展示运行策略的健康诊断矩阵、退化预警流水表与全局调度；
   - **Tab 2: 实验研发任务 (`missions`)**：专注经典的左栏任务索引 + 右栏工作台（ARC 假设流水线/候选池/审核）；
   - **Tab 3: 进化记忆与经验库 (`memory`)**：沉淀 Agent 的量化经验、失败教训与币种模式规则。
2. **Tab 1 自主进化大盘平铺重构**：
   - 顶部提供 4 个轻量状态胶囊；
   - 中部提供策略健康分诊卡片阵列（Opportunity、Stable、Unavailable）；
   - 下部提供整洁高密度的状态表格，点击可直达变体抽屉或模拟盘。
3. **Tab 2 研发任务来源清晰化**：
   - 将隐蔽的来源筛选提至左栏顶部的清晰 Segment 切换器（全部 / ARC / 超参寻优 / Auto-Agent / 投研工作台）。

---

## 2. 详细页面布局与组件拆解

### 2.1 主容器 `AIResearchWorkspace.tsx`
- 顶层 Header：保持标题“AI研发”，右侧提供全局刷新与“新建研究”按钮；
- 主级 Tab 切换栏：
  - `[ 🧬 策略自主进化 (Evolution) ]`
  - `[ 🎯 实验研发任务 (Missions) ]`
  - `[ 🧠 进化记忆库 (Memory) ]`
  - 支持通过 URL query 参数 `?tab=evolution|missions|memory` 保持刷新与路由联动。

### 2.2 Tab 1: `<EvolutionWorkspaceView />` (基于现有 `EvolutionPanel` 平铺改造)
- 不再是一个挤压下方的卡片，而是作为 Tab 内的全宽视图；
- **看板区**：运行状态、退化阈值、评审模式、调度周期 4 个指标卡片；
- **分诊矩阵 (Triage Bar)**：
  - `发现可优化项 (Opportunity)`：翠绿色徽章与策略列表；
  - `观察中 (Stable)`：蓝色徽章；
  - `数据未就绪 (Unavailable)`：琥珀色徽章（注明安全门禁原因：未满14天/样本不足30笔）；
- **诊断明细表**：高密度金融表格，支持快速搜索策略 ID，查看归因覆盖率。

### 2.3 Tab 2: `<ResearchMissionsWorkspaceView />`
- 恢复纯粹清爽的双栏架构：
  - **左侧边栏 (290px)**：
    - 顶部：来源 Segment 切换（全部 / ARC / Optimizer / Auto-Agent / 投研）；
    - 中部：搜索框与状态筛选（全部 / 进行中 / 待审核 / 已结束）；
    - 下部：任务卡片流（支持无限滚动或自适应滚动）；
  - **右侧主工作区**：根据选中任务来源渲染 `ArcConsole`、`ResearchWorkbench` 或 `AILab`。

### 2.4 Tab 3: `<EvolutionMemoryView />`
- 展示 HyperTrade Agent 在多次演化与调优中积累的经验沉淀与避坑模式；
- 提供按标的（如 BTC、ETH）或指标（如 RSI、均线、ATR）检索历史记忆条目。

---

## 3. 验收标准
1. `/ai-lab` 顶部提供清晰的 3 个主 Tab，切换流畅无卡顿；
2. URL 参数 `?tab=evolution` 与 `?tab=missions` 正确驱动激活态；
3. 进入 `missions` Tab 时，上方不再有任何巨大面板挤压，左栏列表与右栏工作台高度自适应窗口；
4. 进入 `evolution` Tab 时，全屏展开清晰的健康分诊大盘与诊断明细表；
5. 前端通过 `tsc && vite build` 0 报错，`eslint` 0 警告。
