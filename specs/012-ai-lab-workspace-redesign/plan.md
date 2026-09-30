# 012 AI 研发工作台空间重构实现计划 (Implementation Plan)

## 1. 涉及工程与文件清单

目标前端仓库：`/Users/jie.feng/Dev/Github/Private/BitPro/frontend/`

```text
frontend/src/pages/
├── AIResearchWorkspace.tsx               # 改造: 引入顶层三段式 Tab (evolution / missions / memory) 与路由联动
└── aiLab/
    ├── EvolutionPanel.tsx                # 重构: 从嵌入式窄卡片改造为 Tab 1 专属全宽健康大盘视图
    ├── EvolutionMemoryView.tsx           # 新建: Tab 3 专属进化记忆与经验库视图
    └── researchTasks.ts                  # 复用/扩展: 任务来源与状态筛选辅助
```

---

## 2. 详细任务分解 (Tasks)

- **T001: 重构 `AIResearchWorkspace.tsx` 顶层导航为三段式 Tab**
  - 在页面头部下方加入 `[ 🧬 策略自主进化 ] [ 🎯 实验研发任务 ] [ 🧠 进化记忆库 ]` Tab 切换器；
  - 使用 `useSearchParams` 中的 `tab` 参数保持状态，默认激活 `evolution` 或记忆的用户选择；
  - 将原有的双栏结构限定在 `tab === 'missions'` 中展示，彻底解除对其他视图的纵向挤压。

- **T002: 重构 `EvolutionPanel.tsx` 为全屏专业自主进化大盘**
  - 去除作为小部件的限制，优化大屏响应式布局；
  - 增加顶部“分诊矩阵 (Triage Matrix)”卡片（可优化 4 项、稳健 1 项、数据积累中 7 项）；
  - 增强诊断表格的可读性与直达跳转链接（直接打开策略详情或模拟盘）。

- **T003: 优化实验研发任务边栏中的来源筛选体验**
  - 在 `AIResearchWorkspace.tsx` 的任务列表上方增加显式的来源 Segment 按钮（全部 / ARC / Optimizer / Auto-Agent / 投研）；
  - 消除底部隐蔽的 `<details>` 折叠菜单。

- **T004: 实现 `EvolutionMemoryView.tsx` 进化记忆与经验库组件**
  - 展示 Agent 历史进化中沉淀的特征记忆条目；
  - 支持按标的、参数类型搜索与过滤。

- **T005: 全量构建与代码质量验收**
  - 执行 `npm run build` 和 `npm run lint` 验证 0 错误通过。
