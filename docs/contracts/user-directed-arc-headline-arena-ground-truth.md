# User-Directed Contract — ARC Headline Arena 外部 Ground Truth 流闭环

> 状态：Active（2026-10-21 启动）。
>
> 激活原因：GitHub Issue #1 由 Headline Arena 官方发起，提议接入其 AI Agent 预测竞技场作为 ARC 的外部 Ground Truth（外生评测与校准）流。产品所有者确认推进接入，为 ARC 自主进化闭环补充外生选择压力与不受自家数据污染的客观前向校验流。
>
> 解决 Issue：Shadowell/HyperTrade#1（ARC 的模拟盘孵化闭环，缺一条外部 ground truth 流）。

## Goal

为 HyperTrade 的通用自主进化内核 ARC（Autonomous Research Core）与模拟盘孵化（Paper Incubation）闭环接入外部第三方真实价格竞技场 Ground Truth 数据流：
1. **外生选择压力**：红蓝博弈防的是内部盲点，但博弈双方共享同一套数据与假设。接引外部竞技场（Headline Arena）对标的（BTC、宏观大宗与指数等）的前向方向预测与真实价格机械结算，为 ARC 候选策略与进化循环提供不受本地数据与过拟合污染的客观评价流。
2. **闭环反思归因**：将外部 Brier 评分、校准曲线与方向判定同步至 ARC 因果归因（`attribution.py`）、反思记忆账本（`reflexion.py`）与演进成效分析（`effectiveness.py`）。
3. **安全与治理硬边界**：在外部网络中断或未配置凭据时保持优雅降级，未观测数据显式保留为未知，绝不伪造评测事实，绝不暴露敏感密钥。

## User-Visible Outcome

1. **外部竞技场客户端与协议**（`ExternalGroundTruthPort` / `HeadlineArenaClient`）：
   - 支持宏观与加密标的挑战发现（`get_active_challenges`）
   - 从候选策略逻辑提取或合成方向预测并前向提交（`submit_prediction`）
   - 获取结算结果与第三方 Brier 评分（`get_challenge_result`）
   - 获取 Agent 宏观校准曲线与胜率统计（`get_agent_calibration`）
2. **ARC 归因与反思层外生信号注入**：
   - `attribution.py` 扩展 `external_ground_truth` 归因维度
   - `findings.py` 与 `reflexion.py` 增加 `EXTERNAL_GROUND_TRUTH_DIVERGENCE` 与 `EXTERNAL_GROUND_TRUTH_UNAVAILABLE` 审查码与纠偏指引
   - `observation.py` 在模拟观察期间支持外生挑战记录与评测同步
3. **只读 API 路由暴露**：
   - `GET /api/v1/arc/ground-truth/challenges`：查询当前活跃的外部预测挑战
   - `GET /api/v1/arc/ground-truth/calibration`：查询当前 Agent 在外部竞技场的校准曲线与 Brier 表现
   - `POST /api/v1/arc/ground-truth/evaluate`：触发针对特定候选或会话的外生对齐评估
4. **Issue 闭环**：通过 Pull Request 关联关闭 `Shadowell/HyperTrade#1`。

## Safety Boundaries

1. **外部不可用容错边界**：网络异常、鉴权失败或外部服务故障时，作为 advisory 维度记录，不得阻断 ARC 控制器或模拟盘的本地执行。
2. **诚实性原则**：缺失、过期或未结算的外部证据显式标注为 `unknown` / `pending`，严禁伪造评分或伪造前向预测。
3. **零密钥泄露**：Headline Arena API Key 与 Secret 仅存于环境配置，不得进入版本控制或公共返回体。
4. **前向约束（Forward-Only）**：已闭合历史窗口不得作为实时预测伪造提交。
