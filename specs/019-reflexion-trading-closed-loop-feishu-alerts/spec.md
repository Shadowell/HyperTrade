# Spec 019: 交易反思闭环 (Reflexion) 与自主进化飞书实时告警联动

## 1. 业务背景与问题 (Context & Problem)

在全自主量化交易 Agent 运行过程中，策略在样本外回测、压力测试对抗、模拟盘（Paper Trading）或实盘（Live Trading）中发生回撤或亏损是常态。
若仅仅将失败策略抛弃或在日志中静默记录，系统无法形成智慧积累；传统系统往往缺乏**交易因果归因**、**负向规则记忆沉淀**以及**自主变异重训**的能力，更容易出现同一错误在不同标的或周期上反复踩坑。
同时，交易团队与系统运维人员需要实时、透明地掌握：
1. 策略在何种宏观行情（Regime）下被击穿；
2. 导致亏损的核心因果（超卖过早抄底、止损过宽、假突破频繁打损）；
3. 算法自主提炼了哪些「负向约束教训 (Negative Constraints)」；
4. 系统自主做出了什么反思变异动作（剪枝解空间、参数自适应重调、下一代策略演化）。

本项目打通「交易反思闭环 (Reflexion) + 飞书实时告警 + RSI/通用策略自主进化」，实现无人值守的自我迭代与全息告警通知。

---

## 2. 核心功能与指标 (Core Capabilities)

### 2.1 结构化交易反思数据模型 (`ReflexionAlertPayload`)
* 记录异常事件标识、触发来源（模拟盘监控、红队对抗测试、回测沙盒）、策略名称与家族（如 `rsi_reversal`）、交易标的与周期；
* 记录触发异常的关键绩效（最大回撤超标、胜率断崖、连续亏损笔数、滑点激增）；
* 记录多状态因果归因报告（牛市高波、熊市低波、高波震荡、低波震荡下的收益分解）；
* 提炼结构化负向约束（Negative Constraints 列表，如 `stop_loss <= 0.05`, `oversold_level <= 20`）；
* 记录自主进化的下一步动作与后代变体 Candidate ID。

### 2.2 飞书富文本交互式消息卡片 (`Feishu Card v2`)
* 生成结构化飞书卡片（`msg_type: "interactive"`）：
  * 红色警示 Header，醒目标题：`🚨 [HyperTrade 交易反思闭环] 触发负向约束提炼与策略进化`；
  * 双列核心字段：策略名称、交易对、时间周期、严重级别；
  * 异常指标板块：展示超标数值与预设阈值对比；
  * 因果归因板块：清晰标注失败时的市场宏观状态（Regime）与失效机理；
  * 负向约束记忆（Reflexion Memory）：结构化列出禁止规则与剪枝条件；
  * 自主进化动作：显示后代候选策略版本与重新训练/验证状态；
  * 底部控制台与回测报告跳转链接；
* 支持纯文本降级备份（`msg_type: "text"`），防止消息超长或第三方 Webhook 限制。

### 2.3 RSI 策略端到端反思与自主进化引擎 (`RsiEvolutionEngine`)
* 针对 RSI 超买超卖反转策略（`rsi_reversal`），构建完整的实战演练闭环：
  1. 生成初代参数（如 `rsi_period=14`, `oversold_level=30`, `stop_loss=0.10`）；
  2. 模拟高波动震荡行情压力，触发回撤与连续亏损异常；
  3. 因果归因引擎定位震荡市过早接飞刀与宽止损缺陷；
  4. 提炼负向约束并写入全局 Reflexion Memory Ledger；
  5. 变异器读取反思记忆，自适应剪枝并进化出新一代参数（如 `rsi_period=21`, `oversold_level=20`, `stop_loss=0.05` 并叠加均线滤波）；
  6. 自动向飞书推送全息反思卡片，并在样本外沙盒中验证性能提升。

### 2.4 REST API 与 CLI 运维工具
* API:
  * `POST /api/v1/arc/reflexion/alerts/test` (发送测试飞书反思卡片)
  * `POST /api/v1/arc/reflexion/dispatch` (分发反思告警)
  * `POST /api/v1/arc/evolution/rsi-cycle` (触发 RSI 自主进化与反思闭环演练)
  * `GET /api/v1/arc/reflexion/history` (查询当前反思记忆与负向约束库)
* CLI:
  * `hypertrade reflexion alert --test`
  * `hypertrade reflexion evolve-rsi --symbol <symbol> [--dry-run]`
  * `hypertrade reflexion list`

---

## 3. 安全与架构边界 (Boundaries & Safety)
1. **Webhook 容错性**：飞书推送失败或网络超时绝对不能阻塞策略交易或回测主循环（fail-open with error logging）；
2. **文本超长保护**：严格遵守飞书 Webhook 限制（单条消息 <= 3900 字符，自动截断并在末尾保留完整控制台链接）；
3. **敏感信息保护**：告警消息与日志严禁打印任何 API Key、Secret、密码或生产环境凭据；
4. **反思规则确定性**：提炼的负向约束必须具备 AST/参数映射能力，避免模棱两可的无用自然语言。
