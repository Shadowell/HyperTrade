# 自进化研究模型选择与终态名额释放

状态：实施；2026-09-26；用户要求研究改用 DeepSeek，并修复失败原因不可见与名额再次卡死。

## 背景
规格 013 部署后，#443 首轮上下文 46,982 通过，但 `codex/gpt-6-astra` 返回 HTTP 400（ChatGPT 账号不支持该模型），`gpt-5.5` 为 free 套餐额度耗尽。自进化创建研究时 provider 写死为 `codex`；失败原因被吞掉；human 模式下“模型不可用”“没有候选”仍永久占用并发名额。

## 需求
- FR-001：`EvolutionConfig.research_provider`（默认 `codex` 兼容旧配置）决定循环创建研究的 provider，研究创建时冻结进目标。
- FR-002：模型调用失败时，停止事件消息附带 HTTP 状态码或异常类别及摘要，按上下文脱敏策略先脱敏再截断。
- FR-003：`avo_provider_unavailable` 与 `avo_no_candidate` 在 human/agent 模式都视为本轮结束并释放名额；未决动作、最终验证未结算及其它需人工核对的原因继续占用；同源冷却不变。
- FR-004：不修改原 Paper、审核模式、门槛或 Live 能力。

## 验收
生产容器验证 DeepSeek 可完成 AVO 工具调用；配置切换后新研究冻结 `deepseek`；HTTP 400 摘要可见且密钥不出现；两种终态冷却后可再准入，未解决原因仍阻断；完整检查通过。
