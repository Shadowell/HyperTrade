# Sprint Contract: Agent Code Workspace (P1-6 自主性基建)

## Sprint Name

`agent-code-workspace`

## Goal

把既有双层沙箱（本地 rlimit+AST+guard / 生产 rootless 容器）暴露为 Agent 的
**代码工作区工具面**：agent 可以逐文件写策略代码与测试、读回、列出、并在沙箱里
跑 ruff/pytest 看真实结果——获得「写代码→跑测试→读错误→修」的 OpenCode 式
迭代能力。这是 ARC 策略空间从 6 家族模板解放为"agent 写真代码"的前置。

## In Scope

- `agent/workspace.py`：`AgentWorkspace`——kernel 作用域的持久文件区
  （dict path→content），写时复用沙箱校验器（路径白名单 strategies//tests/、
  扩展名、256KB 配额、Python AST 禁网络/进程/动态执行——写时即反馈）；
  `run` 把累积文件 + 请求命令提交 `StrategySandbox`（幂等键=内容哈希，
  重放安全），返回结构化命令结果。
- Agent 工具面（registry 单一事实来源）：
  - `workspace.write_file` / `workspace.read_file` / `workspace.list_files` /
    `workspace.run`（read × 2 + research_write × 2）。
- kernel executor 四个分支；system prompt 路由说明。

## Out of Scope

- 生产 UDS 容器 runner 接线（本地 StrategySandbox 为默认后端；生产部署沿用
  既有 sandbox service，接口已兼容 SandboxRunner 协议）。
- ARC codegen 与工作区的融合（后续合同）。
- 交互式/长驻进程执行（沙箱是批式命令模型）。

## Deliverables

- `agent/workspace.py`、`tools/registry.py`、`agent/kernel.py`。
- `tests/test_agent_workspace.py`：路径/扩展/配额/AST 写时拒绝、写读列回环、
  真实 pytest 通过与失败、危险命令参数拒绝、空工作区、幂等重放、治理策略。

## Done Means

- agent 能写一个策略文件+测试文件并在沙箱中跑 pytest 拿到真实通过/失败结果。
- 危险代码（网络 import/eval）在 write_file 即被拒绝并给出原因。
- 相同内容+命令的 run 幂等重放同一 sandbox_run_id。
- `./scripts/check.sh` 全绿。

## Verification

```bash
uv run pytest -q tests/test_agent_workspace.py tests/test_tool_registry.py
./scripts/check.sh
```

## Risks / Notes

- 工作区是 kernel 作用域内存（run 结束即弃），持久化走沙箱 artifacts 账本
  （内容寻址），与既有审计语义一致。
- 沙箱命令各自 20s 超时、单命令失败即停——与既有批式语义一致。

## Handoff

- Next likely step: P1-7 token streaming，或 ARC codegen×workspace 融合。
