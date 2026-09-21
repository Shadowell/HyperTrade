# Implementation Plan: 进化告警可靠性

## Technical Context
Python/FastAPI/SQLAlchemy，现有 EvolutionAlert.payload_json；BitPro React通过管理员代理读取。
不新增调度器、交易写操作或第二套事实源。
## Constitution Check
只读排障，保留Paper；图谱缺失用调用检索补充，不将UNKNOWN当零影响。
## 实施
1. 回执严格校验、每日提醒、旧记录真实投影、中文原因和优先级。
2. 诊断稳定分类：已复现BitPro422点数上限；成本未知继续阻断。
3. BitPro独立切片：高频序列有界读取、告警代理/列表/确认和配置摘要。
4. 定向及完整检查、逻辑提交、各自发布、真实通知与页面验收。
## 数据与兼容
payload增加业务回执版本和提醒计数；delivered_at为最近服务接受时间。
旧sent时间保留但标为未验证，下次提醒更新回执。恢复重现清除本轮尝试/确认信息。
## 验证
test_evolution_alerts、test_evolution_diagnostics、上下游合同与scripts/check.sh。
真实校验只发送实际未解决告警，输出字段白名单，不暴露凭证。
