# Sprint Contract: 运维探活与安全令牌管理 (Spec 032)

## 目标

为 HyperTrade 生产环境提供标准化的运维探活端点（`/healthz`、`/readyz`、`/livez`）与动态安全令牌轮换管理系统（`TokenRotationService`）。保障容器编排（K8s/Docker）、系统守护进程与反向代理的精准健康探测，同时支持无缝令牌轮换与过期预警，杜绝生产密钥硬编码与突发性凭证失效风险。

## 范围与核心交付

1. **容器级运维探活端点 (`/healthz`, `/readyz`, `/livez`)**：
   - `GET /healthz` (与 `/api/healthz`)：
     - 全景系统健康报告：包含系统运行时间 `uptime_seconds`、数据库连通性及延迟 `database` (`SELECT 1` 探测)、各目标适配器状态 `adapters` (BitPro / QuantLab 心跳探测)、`paper_session` 活跃状态与 `security` 令牌统计；
     - 状态码：核心依赖正常时返回 HTTP 200（`"status": "healthy"` 或 `"degraded"`），关键依赖（如数据库故障）返回 HTTP 503（`"status": "unhealthy"`）；
   - `GET /readyz` (与 `/api/readyz`)：就绪探针（Readiness Probe），当数据库正常连接且基本服务就绪时返回 HTTP 200 `{"status": "ready"}`，否则返回 HTTP 503；
   - `GET /livez` (与 `/api/livez`)：存活探针（Liveness Probe），轻量非阻塞快速返回 HTTP 200 `{"status": "alive"}`；
   - 保持现有 `/api/health` 完全兼容向下运作。

2. **安全令牌生命周期与动态轮换引擎 (`TokenRotationService`)**：
   - 在 `backend/src/hypertrade/security/token_manager.py` 实现 `TokenRotationService` 与 `TokenRecord`：
     - 令牌属性：`token_id`、`token_label`、`token_hash` (SHA-256 加盐/哈希)、`token_prefix` (前缀脱敏展示)、`scopes`、`created_at`、`expires_at`、`revoked_at`、`status` (`ACTIVE`, `EXPIRING_SOON`, `EXPIRED`, `REVOKED`)、`usage_count`、`last_used_at`；
     - 签发令牌：`issue_token(label, scopes, ttl_days=30)` 返回持久化元数据与仅单次可显的明文令牌；
     - 令牌验签：`verify_token(plaintext)` 恒定时间 `hmac.compare_digest` 比较，检查过期与撤销状态，自增调用计数；
     - 平滑轮换：`rotate_token(token_id, grace_period_hours=24)` 签发新令牌，旧令牌进入宽限期，在宽限期结束后自动作废，实现客户端热切换无停机；
     - 吊销令牌：`revoke_token(token_id, reason)` 立即作废令牌并记录审计；
     - 过期预警：`audit_expiring_tokens(warning_threshold_days=7)` 扫描即将失效令牌，支撑运维告警。

3. **安全令牌 REST 管理 API**：
   - `GET /api/security/tokens`：查询所有注册令牌的审计元数据（脱敏，AdminUser 守卫）；
   - `POST /api/security/tokens/issue`：签发新服务令牌（AdminUser 守卫）；
   - `POST /api/security/tokens/{token_id}/rotate`：触发令牌热轮换，返回新凭据与过渡期（AdminUser 守卫）；
   - `POST /api/security/tokens/{token_id}/revoke`：紧急吊销指定令牌（AdminUser 守卫）；
   - `GET /api/security/tokens/expiring`：获取临期需要轮换的令牌列表（AdminUser 守卫）。

4. **适配器心跳守护探测 (Target Heartbeat)**：
   - 为目标适配器（BitPro 与 QuantLab）注入 `heartbeat()` 探测；
   - 在 `/healthz` 执行健康聚合时，并发检查适配器状态并上报响应延迟。

## 验收条件

1. `curl /healthz`、`/readyz`、`/livez` 正常返回对应 JSON 报文及 HTTP 200/503 语义状态；
2. `TokenRotationService` 单元测试通过令牌签发、哈希防篡改、平滑轮换宽限期、紧急吊销与过期审计验证；
3. REST 端点在鉴权拦截、Token 动态签发轮换和脱敏返回上满足安全标准；
4. `./scripts/check.sh` 质量门禁 100% 通过（Ruff, Mypy, Frontend, Pytest）。
