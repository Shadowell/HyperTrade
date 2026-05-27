# 10 Deployment / 部署

## English

Deployment uses a single server:

- host Nginx listens on `3333`
- API container binds to `127.0.0.1:3334`
- PostgreSQL/pgvector runs in Docker Compose
- GitHub Actions self-hosted runner label is `hypertrade-production`
- deployment records `/opt/hypertrade/deploy/last_deployed_sha`

Secrets stay in `/opt/hypertrade/.env`. PostgreSQL port is not public.

## 中文

部署使用单台服务器：

- 宿主机 Nginx 监听 `3333`
- API 容器绑定 `127.0.0.1:3334`
- PostgreSQL/pgvector 通过 Docker Compose 运行
- GitHub Actions self-hosted runner label 为 `hypertrade-production`
- 部署成功后记录 `/opt/hypertrade/deploy/last_deployed_sha`

密钥只放 `/opt/hypertrade/.env`。PostgreSQL 端口不对公网暴露。

