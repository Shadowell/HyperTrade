# 09 Frontend Harness / 前端 Harness

## English

The frontend is an operational workbench, not a marketing page. `/harness` shows provider state, tool calls, trace events, RAG, memory, alert channels, and deployment hints.

Runtime data comes from public workbench read endpoints, primarily `GET /api/harness/overview`. That endpoint keeps the page focused on one operator surface: Provider configuration, registered tools, OKX ticker freshness, recent Agent runs, recent trace events, RAG document/chunk counts, and Memory audit counts. The page no longer renders a login form for observability or research workflows; privileged mutations such as provider selection, paper lifecycle controls, live order approval/execution, Memory disable, and Feishu send still require admin session auth at the API layer.

Design direction:

- dense trading-desk layout
- restrained paper/ink/brass palette
- 8px-or-less radius
- lucide icons for controls and state
- Chinese UI by default, English toggle available

## 中文

前端是操作工作台，不是营销页。`/harness` 展示 Provider 状态、Tool Call、trace、RAG、Memory、告警渠道和部署状态。

页面通过公开的工作台读取接口获取运行态，核心入口是 `GET /api/harness/overview`。这个聚合端点让操作路径集中在一个界面里：Provider 配置、注册工具、OKX 行情新鲜度、最近 Agent run、最近 trace、RAG 文档/分片计数、Memory 审计计数。工作台不再为了可观测性和研究流程渲染登录表单；Provider 切换、paper 生命周期控制、实盘审批/执行、Memory 禁用、发送飞书等特权写操作仍在 API 层要求 admin session auth。

设计方向：

- 信息密度较高的交易工作台
- 克制的 paper/ink/brass 配色
- 圆角不超过 8px
- 控件和状态使用 lucide 图标
- 默认中文，提供英文切换
