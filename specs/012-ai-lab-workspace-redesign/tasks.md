# 012 AI 研发工作台空间重构任务清单 (Tasks)

- [ ] **T001: 改造 `AIResearchWorkspace.tsx` 顶层为语义化三段式 Tab**
  - 文件：`BitPro/frontend/src/pages/AIResearchWorkspace.tsx`
  - 任务：引入 `[ 🧬 策略自主进化 ] [ 🎯 实验研发任务 ] [ 🧠 进化记忆库 ]` 选项卡，与 URL `?tab=` 驱动联动。

- [ ] **T002: 重构 `EvolutionPanel.tsx` 为全屏专业自主进化大盘**
  - 文件：`BitPro/frontend/src/pages/aiLab/EvolutionPanel.tsx`
  - 任务：重写为 Tab 1 专属全宽看板，增加分诊矩阵 (Triage Matrix: Opportunity, Stable, Unavailable) 卡片与高密度金融流水表。

- [ ] **T003: 改造实验研发任务左栏来源筛选器**
  - 文件：`BitPro/frontend/src/pages/AIResearchWorkspace.tsx`
  - 任务：将来源（ARC / Optimizer / Auto-Agent / Research）提至左栏顶部作为直观切换 Segment，移除底部隐蔽的 details 菜单。

- [ ] **T004: 实现 `EvolutionMemoryView.tsx` 记忆与经验库视图**
  - 文件：`BitPro/frontend/src/pages/aiLab/EvolutionMemoryView.tsx`
  - 任务：作为 Tab 3 内容展示 Agent 的进化记忆条目、避坑规则与参数有效性沉淀。

- [ ] **T005: 执行前端编译与验证**
  - 命令：在 `BitPro/frontend/` 运行 `npm run build`
  - 任务：确保 0 报错通过编译。
