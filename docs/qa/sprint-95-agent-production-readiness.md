# Sprint 95 — HyperTrade Agent 生产就绪度评测

评测日期：2026-07-14  
评测对象：`main` 的 Codex Provider（`gpt-5.4`）与 HyperTrade Agent runtime  
结论：**架构已达到专业研究型交易 Agent 的设计水准；实际运行尚未达到生产级、尤其未达到自动或实盘交易级。**

当前推荐定位是“受控的交易研究与模拟盘决策支持系统”，而不是可无人值守地运行实盘的交易 Agent。最大的阻塞项不是工具数量，而是 Provider 失败会以未处理的 HTTP 500 结束，使评测与运行都无法可靠地完成和审计。

## 1. 评测边界与方法

所有真实 Provider 请求只通过本机 SSH 转发访问服务器的
`hypertrade-eval`：独立 Compose 项目、独立 PostgreSQL 卷与网络、仅
`127.0.0.1:4334` 监听。它没有生产数据库、Nginx 路由、BitPro 挂载/网关、
后台 worker、交易凭据或 Feishu。生产服务未作为测试目标。

评测使用四类证据：

| 层 | 方法 | 结果 | 可以证明什么 |
| --- | --- | --- | --- |
| 确定性回归 | 隔离 API 的 `/api/evals/status` | **14/14 passed** | 已编排的 fixture、来源/缺失数据披露、主网风险拒绝和报告合约没有回归 |
| Provider 金集 | 24 例版本化 Golden set，真实 Codex Provider | **未完成**：第 11 例返回 HTTP 500 | 真正的端到端可用性尚不能形成完整基线 |
| Provider 核心子集 | 去除 8 个隔离环境不能端到端验证的 BitPro 用例后，运行 16 例 | **未完成**：第 3 例返回 HTTP 500 | 故障不局限于 BitPro 集成 |
| 对抗安全 | 两条越权/注入类真实 Provider 请求；另尝试 Promptfoo | 两条请求均 `200`、`evaluation_mode=evaluation`、无工具调用；Promptfoo 未进入测试 | 未观察到写入或下单；但没有触发“已选择且被拒绝”的真实工具证据 |

Golden set 失败时的服务器堆栈显示 `CodexChatProvider` 的
`httpx.ReadTimeout` 从 `AgentKernel` 一路冒泡至 FastAPI。故障发生在模型请求，
不能归因于 BitPro 工具本身。该调用路径在
[`providers/codex.py`](../../backend/src/hypertrade/providers/codex.py) 中直接
`post`/`raise_for_status`，而
[`agent/kernel.py`](../../backend/src/hypertrade/agent/kernel.py) 的 Planner 调用
没有将该类异常收敛为持久化、结构化的 provider-unavailable 终态。

Promptfoo runner 已显式关闭远程生成、遥测、更新与分享；但首次运行停留在
`npx promptfoo@latest` 的本机依赖拉取阶段，约 7 分钟内没有向隔离 API 发起
测试请求，已停止。本项是 **not run**，绝不是安全通过。

本报告只记录汇总与故障类别；没有将 prompt、模型输出、工具参数、响应原文或凭据写入仓库。生成的轨迹仍留在隔离评测的临时目录。

## 2. 当前实测结论

### 2.1 质量与可靠性

| 维度 | 判定 | 证据与解释 |
| --- | --- | --- |
| 确定性正确性 | Pass | `/api/evals/status` 的 14/14 fixture 测试通过 |
| Provider 可用性 | **Fail / P0** | 两次标准化采集均遇到未捕获 `httpx.ReadTimeout` 并返回 HTTP 500 |
| 完整金集覆盖 | Not achieved | 24 例无法完成；因此无有效工具准确率、F1、p95 延迟、token 或成本基线 |
| 可重复性 | Not achieved | 无法取得两次完整同模型结果，不能设置 CI 阈值 |
| 对抗写入隔离 | Partial pass | 两条真实越权请求均处于 evaluation mode 且没有工具派发；但模型未选择写工具，未观测到拒绝事件 |
| 外部依赖降级 | Fail / P0 | Provider 超时冒泡为 500，没有稳定的错误分类、失败报告或继续执行能力 |
| 生产影响 | Pass | 本次仅触达隔离 API；生产数据库、BitPro、worker 与生产 API 均未被用作目标 |

不要把“14/14 确定性通过”误读为“真实 Agent 14/14 通过”。前者证明受控服务合约；后者需要真实模型、网络、工具和异常路径共同完成，目前恰恰在这里失败。

### 2.2 工具与功能覆盖

`ToolRegistry.default()` 当前有 **46** 个 Agent 可见工具：26 个只读、10 个研究写入、6 个模拟盘写入、1 个测试网订单意图、3 个实盘只读诊断；策略元数据中有 5 个 blocked、1 个 approval-required。工具类别覆盖 OKX 行情、全球市场状态、RAG、审计 Memory、策略库与研究任务、回测、BitPro 策略/回测/模拟盘生命周期、世界模型和实盘只读诊断。

这在研究 Agent 中已经是丰富的工具面，不是“功能太少”的原型系统。其强项是每个工具都有 scope、审批、幂等、来源、超时和失败行为元数据，并由确定性治理层在执行前裁决。关键边界见：

- [Tool Registry](../architecture/04-tool-calling.md) 与
  [`ToolRegistry`](../../backend/src/hypertrade/tools/registry.py)
- [Risk Engine](../architecture/14-risk-engine.md)
- [Testnet execution boundary](../architecture/15-okx-testnet-execution.md)
- [Research / BitPro lifecycle](../architecture/23-autonomous-strategy-research-institution.md)

但丰富度不等于生产成熟度：其中 25 个 BitPro 工具及 3 个实盘诊断工具没有在这套无 BitPro 的隔离目标中完成端到端验证；真实 Provider 也未完成整个 24 例集。当前应表述为“**工具面丰富、验证深度不足**”。

## 3. 架构评审

### 优点：专业研究型 Agent 的正确骨架

1. **可信执行边界正确。** LLM 只规划；`ToolRegistry`、
   `RiskGovernancePolicy`、`RiskEngine` 与确定性 Python 执行器决定是否真正访问数据库、BitPro 或交易路径。未知工具默认拒绝。
2. **交易安全没有交给 prompt。** 写入有 scope/审批/幂等要求；主网被阻断，实盘路径是测试网订单意图与人工批准，而非让模型直接下单。
3. **研究证据链完整。** RAG、长期 Memory、策略卡、ResearchMandate、验证门、BitPro 结果引用、模拟盘观察与 WorldState 被设计为可审计的实体，而不是把状态留在聊天上下文。
4. **可观测与隐私边界清楚。** Flight Recorder/Trace 保留摘要和政策结果；可选 Langfuse 导出排除 prompt、回答、私有推理、工具参数和凭据。
5. **评测隔离意识正确。** evaluation mode 在内核边界拒绝非只读工具；服务器目标也与生产组件和数据分离。详见 [Agent Evaluation Foundation](../architecture/26-agent-evaluation-foundation.md)。

### 关键缺口：从“合理设计”到“生产系统”的最后一公里

1. **失败收敛不完整（P0）。** Provider timeout 变成 500，既没有可靠的 run 终态，也无法保留统一的失败分类和可重试证据。这是当前最直接的生产阻塞项。
2. **评测运行器遇一例失败即中断（P0）。** 无法区分 planner 选错、工具超时、Provider 超时、上游数据不可用与测试基础设施问题；也无法得到一个有分母的成功率。
3. **外部集成没有隔离的可运行替身（P1）。** 不连接 BitPro 是正确的安全选择，但需要受控 fake MCP/record-replay 或专用测试租户，才能评测那 8 个工具路径。
4. **安全实测仍不充分（P1）。** 当前真实对抗 prompt 被模型直接拒绝、未选工具；这说明未见绕过，却不能证明“选中写工具后一定记录 denied”的真实 Provider 路径。确定性测试有此覆盖，但还缺真实模型证据。
5. **交易研究验证还不是绩效证明（P1）。** 还没有版本化 holdout、walk-forward、成本/滑点/资金费假设的可比回测基线，亦没有实盘经纪商可靠性、灾备、限频、对账和操作 SLO 的实测证据。

## 4. 与专业交易 Agent / 量化运行时的对比

下面是能力与证据口径的比较，**不是收益率排名**。公开系统的模型、数据、样本期、交易成本、资产范围和执行假设都不同，不能把论文回测收益与 HyperTrade 的工具 F1 或未来收益相减。

| 参照系统 | 已公开的专业能力/评测证据 | HyperTrade 现状 | 差距或优势 |
| --- | --- | --- | --- |
| [TradingAgents](https://arxiv.org/abs/2412.20138) | 基本面、情绪、技术、交易员与风控等角色协作；开源项目使用 LangGraph；项目明确定位为研究用途 | 单一 Provider planner + 强确定性工具/治理/审计边界 | HyperTrade 的执行治理更清晰；角色化的研究辩论、独立 critic/风险委员会与跨角色评测较弱 |
| [FinRobot](https://arxiv.org/abs/2405.14767) | Data-CoT、Concept-CoT、Thesis-CoT 的多层金融研究/估值流程，整合定量和定性分析 | 有 RAG、Memory、策略研究、验证门和报告，但真实 Provider 基线未稳定 | 应补充可替换的分析/批判角色及有版本的数据、估值/财报/新闻来源；不应以多 Agent 数量替代确定性门禁 |
| [FinAgent](https://doi.org/10.1145/3637528.3671801) | 数值、文本、图像多模态市场信息，工具增强、反思与记忆；论文在 6 个数据集报告了金融指标比较 | 当前主力是 OKX/BitPro、RAG 和全球状态，尚无同口径多模态、跨数据集、walk-forward 结果 | 研究能力和公开可比数据基准是主要差距。论文报告的收益改进仅适用于其数据/假设，不能视为可比生产收益 |
| [QuantConnect LEAN](https://www.quantconnect.com/docs/v2/lean-engine/getting-started) | 文档化的研究、回测、实时数据、订单处理、经纪商连接和本地/云部署；有明确的 live-trading 操作手册与多经纪商列表 | 当前刻意只到测试网订单意图和人工审批，实盘写入仍阻断 | 这是正确的安全阶段；若目标是生产执行，需要补齐连接恢复、对账、告警、运行时 SLO、灾备和经纪商/交易所集成验证。LEAN 不是 LLM Agent，因此只作运营成熟度参照 |

**比较结论：** 与 TradingAgents、FinRobot、FinAgent 相比，HyperTrade 不输于“把 LLM 接上金融工具”的架构思路，且在确定性风险边界、审计和不直接放开实盘方面更接近严肃系统。差距集中在可重复的真实评测、跨数据研究基准、多角色研究分工和运行可靠性。与 LEAN 这类生产量化运行时相比，HyperTrade 的研究治理设计不错，但执行运营成熟度尚有明显距离。

## 5. 专业度分级

| 能力 | 评级 | 说明 |
| --- | --- | --- |
| 架构与安全治理 | B+ | 边界、审批、幂等、来源与审计设计专业 |
| 工具广度 | B | 46 个工具覆盖研究到模拟盘/测试网；但大量路径尚未真实验收 |
| 数据与研究方法 | B- | 有证据链和验证门设计；缺少公开、版本化、可复现的多数据集/walk-forward 证据 |
| 可观测性与评测设计 | B- | 分层思路正确；真实 Provider 基线、Promptfoo 和完整故障分类未跑通 |
| 真实运行可靠性 | D | 已观察到 Codex timeout 未捕获并导致 HTTP 500 |
| 自动/实盘执行就绪度 | 不通过（设计上禁用） | 当前应继续保持 mainnet 禁用，不应宣称 production live-ready |

综合等级：**L2 — 受控研究/模拟盘就绪（总体 C+）**。

- 可以称为：专业研究型交易 Agent 的架构与受控实验平台。
- 不应称为：已完成生产验证的自动交易 Agent、实盘交易 Agent，或有可比收益优势的 Agent。
- 达到 L3（生产执行就绪）的前提是先清除下述 P0，并完成受控集成、重复性、运行 SLO 与人工运营演练。

## 6. 达到生产级的优先级路线

### P0：先让一次失败也可审计、可继续、可恢复

1. **收敛 Provider 异常。** 将 `httpx.TimeoutException`、请求错误和非 2xx
   响应转为 typed provider error；`AgentKernel` 必须持久化
   `provider_unavailable`/`failed`、错误类别、可重试性和安全摘要，并返回结构化 API 结果而非 500 堆栈。
2. **让金集采集 fail-soft。** 每一例都落一条去敏轨迹和 failure taxonomy，完成其余用例；报告分别给出 planner accuracy、工具/数据可用性和端到端成功率，不能把基础设施失败算作模型选错。
3. **固定评测工具链。** 将 Promptfoo 锁定为受审版本/本地依赖或预构建镜像，避免 `npx @latest` 在评测时安装；要求 2 条对抗测试实际执行并保留安全投影。
4. **设定发布前证据。** 同一 golden set、同一模型至少连续 3 次完成；0 个未处理 5xx；报告成功率、p50/p95、token、失败分类和安全拒绝覆盖。完成后才讨论 CI 阈值。

### P1：补齐集成与研究的“深度”

1. 建立 BitPro fake MCP/录制回放或独立测试租户，使 8 个 BitPro/实盘诊断金集用例可重复执行而不接触生产数据。
2. 加入 Provider 超时预算、取消、退避重试、熔断、可选的受控 fallback，以及按 Provider/模型维度的 error budget。
3. 增加真实 Provider 的“写工具被选择 → evaluation gate denied → 无副作用”的强制测试，而不仅是模型自行拒绝。
4. 把 ResearchMandate 的数据版本、样本内/验证/锁定样本外窗口、费用/滑点/资金费和随机种子作为版本化评测输入；使用 walk-forward 与失败策略样本，而非只测试顺利路径。

### P2：再决定是否需要更多 Agent 角色

优先引入可测的角色职责，而不是为了“多 Agent”而多 Agent：数据完整性审查、策略 critic、风险 reviewer、研究复现 reviewer。每个角色输出应进入同一证据账本，并能被确定性门禁反驳。等 P0/P1 稳定后，再把全球宏观、财报/新闻/多模态资料和组合归因纳入版本化数据基准。

## 7. QA 签核

| 检查项 | 状态 | 证据 | 结论 |
| --- | --- | --- | --- |
| 隔离边界 | Pass | 独立 Compose、数据库、网络、loopback API、无 worker/BitPro/生产数据 | 评测没有扩大到生产 |
| 确定性 Agent 回归 | Pass | `/api/evals/status`: 14/14 | 合约层有效 |
| 24 例真实 Provider 金集 | Fail | 第 11 例 HTTP 500；`httpx.ReadTimeout` 未捕获 | 不可作为发布基线 |
| 16 例核心子集 | Fail | 第 3 例 HTTP 500 | 不是单一外部工具问题 |
| Promptfoo 对抗套件 | Not run | `npx` 依赖获取未完成且未向目标发请求 | 必须固定依赖后重跑 |
| 手工真实对抗请求 | Partial pass | 2/2 完成、evaluation mode、0 工具派发 | 未见绕过；拒绝事件未被覆盖 |
| 生产级自动/实盘交易 | Fail / intentionally disabled | Testnet + 审批边界，mainnet 未启用 | 维持禁用 |

本 sprint 的交付是一次如实的成熟度评审，不是交易绩效认证或投资建议。下一次评测应在 P0 修复后重跑同一份 Golden set，并以本报告的失败项作为必须清零的回归门。
