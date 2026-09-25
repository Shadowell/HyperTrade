# 011 模拟盘策略变体 A/B 对决与分叉接力系统规格 (Paper Variant A/B Testing & Fork Relay)

## 1. 业务目标与背景

在量化交易研究与生产环境中，交易员的主要工作界面集中在 **「模拟盘（Paper Trading）」**。策略大多由 AI 或量化引擎生成，交易员核心关注的是策略在实时行情中的实盘盈亏、最大回撤与成交质量。

当原策略（Baseline）出现性能退化（如 RSI 震荡假突破过多、止损过窄导致滑点磨损）时，HyperTrade 自主进化引擎会生成优化后的候选变体（Variant）。

为了让交易员能以最低认知成本识别问题、比对优化方案，并在未来真实行情中验证变体，本系统提供：
1. **模拟盘概览页「孪生卡片组 (Twin Family Card)」**：将母策略与派生变体聚合为同一家族，在列表页即可一眼识别组属与分叉以来的超额收益（Alpha）。
2. **模拟详情页「AI 进化专区与 A/B 深度比对抽屉」**：在实盘监控页面内直接呈现参数 Diff、同窗双曲线叠图与 Agent 调优因果解释。
3. **「数据基础与资金分叉接力 (Fork Relay)」**：变体启动时继承母策略当前动态总权益（Equity）与历史收益轨迹，在分叉点展开公平、同量纲的 A/B 实时对决。

---

## 2. 核心架构与系统职责

```mermaid
flowchart TD
    subgraph BitPro Frontend (Live Trading)
        D["模拟盘概览页 (InstanceDashboard)<br/>孪生卡片组: 母策略 + 派生变体"]
        M["模拟盘详情页 (InstanceMonitor)<br/>状态胶囊 + 进化专区"]
        W["A/B 深度比对抽屉 (VariantComparisonDrawer)<br/>参数Diff + 双曲线叠图 + 归因解释"]
    end

    subgraph BitPro Backend Gateway (:8889)
        P1["/api/v1/paper/instances/{id}/fork<br/>分叉接力创建变体实例"]
        P2["/arc/evolution & /arc/missions<br/>代理转发 HyperTrade 诊断与候选数据"]
    end

    subgraph HyperTrade Agent Core (:3334)
        H1["自主进化引擎<br/>退化诊断、归因报告、变体生成"]
        H2["回测与同窗核验引擎<br/>IS/OOS 盲测、过拟合防范"]
    end

    D --> M
    M --> W
    W -->|一键启动并行模拟盘| P1
    M -->|读取进化状态与候选| P2
    P2 --> H1
    P1 -->|继承 Base 当前净值| P2
```

---

## 3. UI/UX 详细交互规格

### 3.1 概览列表：孪生卡片组 (Twin Family Card)
- **文件位置**：`BitPro/frontend/src/pages/liveTrading/InstanceDashboard.tsx`
- **呈现规则**：
  - 当某个模拟实例存在派生变体（或其本身是变体）时，启用**家族聚合卡片**。
  - 外层容器显示主策略名称，并在右上角带有徽章：`[ 🧬 1 个变体验证中 ]`。
  - 内部划分为双联分栏：
    - **左侧：母体基准 (Baseline)**：显示当前净值、总收益率、分叉以来的表现（如 `+1.0%`）。
    - **右侧：AI 变体 (Variant)**：带有紫色高光边框和 `Gen-2` 标签，显示变体净值、总收益率、分叉以来的表现（如 `+4.2%`），并以高亮绿色徽章凸显**超额收益 (Alpha: ▲ +3.2%)**。
  - **快捷操作**：
    - `[ 📈 展开双曲线 ]`：就地展开简易迷你净值对照图。
    - `[ 👑 采纳变体 ]`：当变体表现持续跑赢，一键升级为主策略。
    - `[ 🗑️ 终止变体 ]`：独立关闭变体实例，不影响原策略。

---

### 3.2 模拟详情页：状态胶囊与进化专区
- **文件位置**：`BitPro/frontend/src/pages/liveTrading/InstanceMonitor.tsx`
- **页面顶部 Header**：
  - 实例状态旁增加 Agent 胶囊：
    - 发现变体：`[ 🧬 AI 发现可优化项 · 预期夏普 +0.68 ]`（呼吸高亮）。
    - 正常观察：`[ 🧬 AI 监控中 · 累计 64 笔真实成交 ]`。
- **正文专区（`<InstanceEvolutionPanel />`）**：
  - 位于策略参数折叠栏下方、K线复盘上方。
  - **诊断洞察 (Diagnosis Insight)**：自然语言说明策略当前的瓶颈（例如：“RSI 频繁在 30 附近震荡产生假突破，近 14 天磨损 -4.8%”）。
  - **变体快照卡片 (Variant Snapshot)**：显示候选变体 ID、生成时间、预期指标改善（夏普 1.18 -> 1.86，最大回撤 -14.6% -> -7.8%）。
  - **核心按钮**：
    - `[ 🔍 展开 A/B 深度比对工作台 ]`
    - `[ 🚀 一键启动并行模拟盘 (独立资金接力) ]`

---

### 3.3 A/B 深度比对抽屉（`<VariantComparisonDrawer />`）
- **区域 1：Agent 调优意图与因果归因**：
  - 说明“为什么改”、“改动了什么机制”、“预期防范哪类亏损”。
- **区域 2：参数 Diff 对比表（`<ParameterDiffTable />`）**：
  - 逐行对比基线与变体参数，绿色/蓝色高亮修改项，附带每个参数修改的微观意图说明。
- **区域 3：ECharts 同窗双曲线与分叉接力图（`<ForkRelayEquityChart />`）**：
  - 蓝线（Base） vs 紫线（Variant）。
  - 分叉点（Fork Point）竖直虚线标注。
  - 样本内外（IS/OOS 70%/30%）切分标记。
  - 假突破标记点：标记变体成功过滤的无效磨损位置。
- **区域 4：核心量化指标矩阵**：
  - 累计收益率、夏普比率、最大回撤、交易次数、盈亏比、手续费摩擦节约。

---

## 4. 数据基础与资金继承机制 (Fork Relay Specification)

1. **初始资金对齐 (Capital Equity Alignment)**：
   - 变体模拟盘创建时，`initial_equity` **不重置为 0，也不重置为初始默认的 1000U**，而是直接捕获 Base 策略当前的**动态总权益 `current_equity`**（例如 `$1,142.50 USDT`）。
   - 变体继承后的收益率计算公式：
     - **全生命周期累计收益率**：`Total_Return = (Current_Variant_Equity - Base_Initial_Equity) / Base_Initial_Equity`
     - **自分叉以来的超额收益 (Alpha)**：`Alpha_since_fork = (Variant_Return_since_fork) - (Base_Return_since_fork)`
2. **仓位无缝过渡 (Position Handling)**：
   - 采用**纯现金独立接力模式**：变体启动瞬间，原策略的持仓不强行接盘（防止旧策略的套牢单污染变体）。变体以等额的 `$1,142.50` 现金池等待符合新变体逻辑的**第一个新开仓信号**。
3. **历史净值曲线拼接 (Curve Stitching)**：
   - 在图表渲染时，变体在 `[0, Fork_Time]` 这一段完全复用 Base 策略真实采样点；
   - 在 `(Fork_Time, Now]` 这一段绘制变体真实成交累积的净值轨迹。

---

## 5. 验收标准 (Acceptance Criteria)

1. **概览页识别度**：
   - 存在变体时，在 `InstanceDashboard` 中以孪生聚合卡片展示，视觉上明确归属为同一策略家族。
   - 封面直接显示自分叉以来的超额收益率（Alpha）。
2. **模拟详情页交互**：
   - `InstanceMonitor` 顶部出现 Agent 状态胶囊，正文嵌入进化专区卡片。
   - 点击可流畅展开 A/B 深度比对抽屉，参数 Diff 表正确渲染差异项与意图。
3. **数据继承性**：
   - 变体创建后，起始资金严格等于分叉时 Base 策略的实时权益，净值图在分叉点平滑分支，不出现断崖跳变。
4. **系统安全性与隔离**：
   - 启动并行变体绝不修改、中断、重置原 Base 模拟盘。
   - 前端代码通过 BitPro 现有 TypeScript + ESLint 校验，组件按规范组织。
