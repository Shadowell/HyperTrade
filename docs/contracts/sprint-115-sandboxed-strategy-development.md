# Sprint 115 - Sandboxed Strategy Development

> 状态：Completed locally；Gate L 的生产激活项保持 fail-closed，等待 Sprint 116 的 rootless
> container deployment canary。

## Goal

让 Agent 能在隔离、临时、无 secrets、无网络、无 Docker socket、无交易权限的 workspace 中生成
策略 patch，运行白名单 lint/test/limited backtest，并形成可审计 artifact/import manifest。只有人工
审核精确 patch/hash 后才能形成 BitPro import proposal；本 Sprint 不自动导入或执行交易。

## In Scope

- SandboxRequestV1、CommandSpecV1、SandboxRunV1、SandboxCommandResultV1、SandboxArtifactV1、
  PatchManifestV1、ImportReviewV1。
- ephemeral workspace；只允许 `strategies/`、`tests/` 下 `.py/.json/.yaml`，禁止路径穿越、
  symlink、binary 和主仓库直接写入。
- 生产 adapter 优先 rootless Docker；本机/CI 使用等价受限 subprocess adapter，显式清空环境、
  临时 HOME、固定 cwd、关闭 stdin、资源/时间/输出限制、命令 argv 白名单。
- 默认 network deny；禁止 shell string、curl/wget/nc/ssh、package install、Docker CLI/socket、
  interpreter `-c`、任意绝对路径和非白名单 executable。
- unified diff、文件 hash、command/exit/duration/truncation ledger 和 artifact content hash。
- source-file、patch、command-output 和 manifest 的 `SandboxArtifactV1` metadata ledger；workspace
  内容不会留在主仓库或数据库。
- lint、pytest 与 limited deterministic SDK/backtest contract；失败不得标为 validated。
- Import manifest 绑定 Mission/assignment/context/artifact/patch/test hashes、target contract 和
  idempotency key；管理员 accept/reject append-only。Accept 仍仅为 proposal，不调用 BitPro。
- migration `0027_agent_sandbox`；authenticated create/run/list/review API；默认 feature flag off。

## Out of Scope

- 生产 shell、网络搜索、pip/npm/apt、Docker socket、宿主机仓库写入。
- 自动应用 patch、自动 merge、自动 BitPro import、自动 paper/live/order/capital action。
- 任意用户代码长期运行、GPU/大内存或无限输出。

## Done Means

- sandbox 环境中无生产 env/secrets、Docker socket、宿主 SSH/credential 路径。
- 非白名单命令、参数、路径、symlink、network/package/Docker 尝试在启动前拒绝。
- timeout/resource/output limit 强制终止并记录 typed failure；workspace 总大小和文件数受限。
- patch 只能覆盖允许目录/扩展名，hash/diff 可重放，不能修改主仓库。
- lint/test/backtest 全通过才产生 `validated` manifest；伪造 command result/hash 被拒绝。
- review 精确绑定 import manifest；幂等且 append-only，accept 不触发外部写入。
- 生产/预发布 APP_ENV 下拒绝宿主 subprocess fallback；没有 rootless container adapter 时 API
  返回 503，而不是降级执行。
- 全仓检查、migration 往返、production flag-off 和隔离 canary 通过。

## Verification

```bash
uv run pytest tests/test_strategy_sandbox.py tests/test_sandbox_isolation.py -q
uv run pytest tests/test_multi_agent_supervisor.py tests/test_mission_artifacts.py -q
./scripts/check.sh
```

Required scenarios: happy patch/test, path traversal, symlink, forbidden extension, secret absence,
network/Docker/package/shell denial, interpreter `-c` denial, timeout, output truncation, workspace
quota, failed test, hash tamper, idempotent review, accept-no-import, SQL/API and restart projection.

Focused acceptance completed locally: `19 passed`; Ruff and strict mypy passed. The subprocess
adapter now writes command output to a bounded temporary file, kills the complete process group on
timeout, limits process count, records `output_bytes`, and keeps production/staging fail-closed.
SQL projection includes `agent_sandbox_artifacts` and API rejects unknown Mission artifact refs.

## Handoff

Gate L local contract is closed. Production activation still requires a rootless container canary
with network namespace denial, read-only filesystem, cgroup/pids limits and no host Docker socket.
Sprint 116 may add that deployment adapter and the operator UX, but cannot loosen the review boundary.
