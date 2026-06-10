# 09 Frontend Harness / 前端 Harness

## English

The frontend is an operational workbench, not a marketing page. `/harness` is intentionally a core console for Agent runs, report reading, tool trace, RAG, Memory, OKX market snapshot, and recent runs.

Runtime data comes from public workbench read endpoints, primarily `GET /api/harness/overview`. That endpoint keeps the page focused on a small operator surface: default provider status, OKX ticker freshness, recent Agent runs, recent trace events, RAG document/chunk counts, and Memory audit counts. The page no longer renders a login form for observability or research workflows. Advanced controls such as provider selection, paper lifecycle controls, live order approval/execution, strategy/backtest forms, eval panels, Memory disable, and Feishu send are intentionally not first-class UI controls; privileged mutations still require admin session auth at the API layer where they are exposed.

Design direction:

- dense trading-desk layout
- restrained paper/ink/brass palette
- 8px-or-less radius
- lucide icons for controls and state
- Chinese UI by default, English toggle available

## 中文

前端是操作工作台，不是营销页。`/harness` 刻意收敛为核心控制台，只展示 Agent 运行、报告阅读、工具 trace、RAG、Memory、OKX 行情快照和最近运行。

页面通过公开的工作台读取接口获取运行态，核心入口是 `GET /api/harness/overview`。这个聚合端点让操作路径集中在一个较小界面里：默认 Provider 状态、OKX 行情新鲜度、最近 Agent run、最近 trace、RAG 文档/分片计数、Memory 审计计数。工作台不再为了可观测性和研究流程渲染登录表单；Provider 切换、paper 生命周期控制、实盘审批/执行、策略/回测表单、评测面板、Memory 禁用、发送飞书等高级控制不再作为首屏/主页面功能，仍暴露的特权写操作继续在 API 层要求 admin session auth。

设计方向：

- 信息密度较高的交易工作台
- 克制的 paper/ink/brass 配色
- 圆角不超过 8px
- 控件和状态使用 lucide 图标
- 默认中文，提供英文切换
