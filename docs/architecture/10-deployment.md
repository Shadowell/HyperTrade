# 10 Deployment / 部署

## English

Deployment uses a single server:

- host Nginx listens on `3333`
- API container binds to `127.0.0.1:3334`
- PostgreSQL/pgvector runs in Docker Compose
- GitHub Actions self-hosted runner label is `hypertrade-production`
- deployment records `/opt/hypertrade/deploy/last_deployed_sha`
- server-local CLI wrapper `hypertrade`/`ht` runs a short-lived remote client
  container against `http://api:3334`

Secrets stay in `/opt/hypertrade/.env`. PostgreSQL port is not public. BitPro MCP
tokens, provider keys, OKX credentials, and admin credentials must never be
committed.

The optional `cli` Compose profile builds `hypertrade-tui:latest` from the Docker
`tui` target. It never runs as a daemon. The host wrapper selects that service only
for `hypertrade tui`; API and worker keep using the dependency-minimal production
target, so deploy replacement cannot kill the operator TUI process.

## Isolated Evaluation Deployment

The server-side evaluation target is a separate Compose project, not a
production deployment mode. It lives at `/opt/hypertrade-eval` and uses the
`hypertrade-eval` project/network, `hypertrade-eval-*` container names, a
separate PostgreSQL data directory, and `127.0.0.1:4334`. It has no Nginx site,
no production database/data bind mount, and no BitPro host-gateway mapping.

The default evaluator starts only PostgreSQL and API; its worker is an explicit
`background` profile so background market ingestion, paper trading, and monitor
scheduling do not run during a baseline. Paper, monitors, BitPro connectivity,
Feishu, Langfuse, and private exchange credentials are disabled in its
server-only `.env`. A server Codex auth file may be mounted only into the
evaluation API as a read-only Compose secret.

Use the production-built `hypertrade-api:latest` image as the isolated API image.
`deploy/deploy-eval.sh` additionally builds the `agent-eval` Docker target as
`hypertrade-agent-eval:latest`; only that image contains Ragas and evaluation
scripts. Baseline commands run inside this pinned image and never depend on a
host Python/`uv` installation. This gives logical isolation on the same host; a
separate VM/server is required when physical isolation is required.

## 中文

部署使用单台服务器：

- 宿主机 Nginx 监听 `3333`
- API 容器绑定 `127.0.0.1:3334`
- PostgreSQL/pgvector 通过 Docker Compose 运行
- GitHub Actions self-hosted runner label 为 `hypertrade-production`
- 部署成功后记录 `/opt/hypertrade/deploy/last_deployed_sha`
- 服务器本地 CLI wrapper `hypertrade`/`ht` 会启动短生命周期 remote client
  container，连接 Compose 网络内的 `http://api:3334`

密钥只放 `/opt/hypertrade/.env`。PostgreSQL 端口不对公网暴露。BitPro MCP
token、provider key、OKX 凭证和 admin 凭证不能提交到仓库。

可选 `cli` Compose profile 从 Docker `tui` target 构建
`hypertrade-tui:latest`，但不常驻运行。宿主 wrapper 仅在执行
`hypertrade tui` 时选择该 service；API/Worker 继续使用不含 Textual 的生产 target，
部署替换 API 容器不会终止操作员的 TUI 进程。

## 独立评测部署

服务器评测目标是独立 Compose 项目，不是生产模式的开关。它位于
`/opt/hypertrade-eval`，使用 `hypertrade-eval` 项目/网络、
`hypertrade-eval-*` 容器名、独立 PostgreSQL 数据目录和
`127.0.0.1:4334`。它不配置 Nginx、不挂载生产数据库/数据目录，也不映射
BitPro 宿主机网关。

默认只启动 PostgreSQL 与 API；Worker 仅作为显式 `background` profile
保留，因此基线评测不会持续抓取行情、运行模拟盘或监控。评测 `.env` 禁用
paper、monitor、BitPro、Feishu、Langfuse 和私有交易所凭证。服务器 Codex
认证文件仅可作为只读 Compose secret 挂载到评测 API。

隔离 API 复用已经构建完成的 `hypertrade-api:latest` 镜像。
`deploy/deploy-eval.sh` 另行构建 `agent-eval` target，得到
`hypertrade-agent-eval:latest`；只有该镜像包含 Ragas 和评测脚本。基线命令在
固定镜像内运行，不依赖宿主机 Python/`uv`。该方案在同一台主机上提供逻辑隔离；
若需要物理隔离，必须使用独立 VM/服务器。
