# Sprint 109 QA — Champion–Challenger Paper Incubation

## Verdict

PASS。Gate G 关闭。Paper cohort 是 committed research facts 的只读、版本化比较投影；没有
paper lifecycle、订单或资金授权路径。生产无完整可比 cohort 时正确 fail closed。

## Contract Coverage

| 门禁 | 证据 | 结果 |
|---|---|---|
| 固定分母 | 生产 intake 3；0 eligible 成员仍保留 reason | PASS |
| 严格可比 | market/symbol/timeframe/cost/horizon/bucket/policy 精确 key；不同 cost fixture 拆组 | PASS |
| 非单收益排名 | 高 return 但证据/风险较差 fixture 不成为 Champion | PASS |
| 最小 cohort | 单成员 group 只产生 Watch；生产 0 comparable 时无 proposal | PASS |
| 不可变与幂等 | cohort key/version/source/content 唯一约束；重复 build 返回同一 id | PASS |
| 人工且有时效 | accept/reject/hold 独立审计；过期 proposal 返回冲突 | PASS |
| 执行隔离 | 静态 import 审计与业务表前后计数 | PASS |
| 多界面同投影 | REST、CLI、Textual、Web 均调用 `PaperCohortService` | PASS |

## Automated Evidence

- `tests/test_paper_cohorts.py`: 8 passed。
- `./scripts/check.sh`: frontend lint、9 tests、production build；Ruff；mypy 147 source files；
  514 Python tests，全部通过。
- 临时 PostgreSQL：全链 upgrade、`0021 -> 0020 -> 0021` 往返、最终两张 cohort 表存在。

## Production Evidence

- Commit `22dbc3c1a7c07e743b4e6c1ecd5ab1aa69eb4bbb`；workflow `29390025815` success。
- API/Nginx health、Alembic `0021_paper_cohorts (head)`、`/harness/portfolio` HTTP 200、近五分钟
  API/worker 日志无 traceback/exception/critical/error。
- cohort `pcoh_cbf6b383e7b448d7a36f`：window `pwin_c23b2d48cfab40eeb3f9`、version 1、
  intake 3、comparable 0、proposal 0、status `needs_data`、execution/paper lifecycle false。
- 相同请求和幂等键重放 `same_id=true`、`idempotent=true`。
- 前/后计数：PaperPromotion 0/0、PaperReviewRequest 0/0、label decision 0/0、paper order
  10/10、live intent 1/1；唯一预期写入是一个 immutable cohort snapshot。

## Residual Risk

- 生产尚无两个完整、同口径、未过期的 paper members，因此 Champion/Challenger 正向路径由
  deterministic fixtures 覆盖，生产只验收 fail-closed 路径。这是当前事实，不应通过伪造数据绕过。
- label accept 仍仅表示同意研究标签；任何未来 paper/live/capital 动作必须另有合同和权限门禁。
