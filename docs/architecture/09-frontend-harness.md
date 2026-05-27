# 09 Frontend Harness / 前端 Harness

## English

The frontend is an operational workbench, not a marketing page. `/harness` shows provider state, tool calls, trace events, RAG, memory, alert channels, and deployment hints.

Runtime data comes from `GET /api/harness/overview` after admin login. That endpoint keeps the page focused on one teaching surface: Provider configuration, registered tools, OKX ticker freshness, recent Agent runs, recent trace events, RAG document/chunk counts, and Memory audit counts. The page keeps a preview mode for unauthenticated learning, then replaces it with live data once the session is valid.

Design direction:

- dense trading-desk layout
- restrained paper/ink/brass palette
- 8px-or-less radius
- lucide icons for controls and state
- Chinese UI by default, English toggle available

## 中文

前端是操作工作台，不是营销页。`/harness` 展示 Provider 状态、Tool Call、trace、RAG、Memory、告警渠道和部署状态。

登录后页面通过 `GET /api/harness/overview` 获取运行态。这个聚合端点让学习路径集中在一个界面里：Provider 配置、注册工具、OKX 行情新鲜度、最近 Agent run、最近 trace、RAG 文档/分片计数、Memory 审计计数。未登录时保留预览模式，登录成功后切换到真实数据。

设计方向：

- 信息密度较高的交易工作台
- 克制的 paper/ink/brass 配色
- 圆角不超过 8px
- 控件和状态使用 lucide 图标
- 默认中文，提供英文切换
