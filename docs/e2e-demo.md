# 端到端演示（M4 / M19）

两条路径：

1. **默认验收（无真 App）**：`USE_FIXTURES=true` + 本地 HMAC webhook → `202` → `/console` 从 **Postgres** 看到 job（见 README「无真 App smoke」与 `scripts/smoke_fixtures_webhook.py`）。
2. **可选真 App**：GitHub App → smee 转发 → 安装到测试仓 → 开 PR → 看控制台与 sticky 评论（下文步骤 1–6）。

## 前置

- Docker / Compose，或本机 Redis + Postgres + Python 3.11+
- 真 App 路径额外需要：Node（`npx smee`）、有管理权限的测试仓库

## 1. 创建 GitHub App（可选 · 真 App）

1. GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**
2. **Webhook URL**：先去 [smee.io](https://smee.io/) 新建 channel，把 URL 填到 App Webhook
3. **Webhook secret**：自拟长随机串，稍后写入 `.env` 的 `GITHUB_WEBHOOK_SECRET`
4. 权限建议：
   - Repository permissions：Contents (Read)、Pull requests (Read & write)、Issues (Read & write)
5. Subscribe to events：勾选 **Pull request**
6. 创建后记下 **App ID**，生成并下载 **Private key**（PEM）

## 2. 安装 App 到测试仓（可选）

App 页 → **Install App** → 选择测试组织/用户 → 仅选测试仓库 → Install。

## 3. 启动 PR Sentinel

```bash
cp .env.example .env
# 编辑 .env：
#   GITHUB_WEBHOOK_SECRET=<与 App Webhook Secret 相同，或本地 smoke 自拟>
#   ADMIN_TOKEN=<控制台鉴权用长随机串>
#   USE_FIXTURES=true          # 无真 App 默认验收
#   # 真 App 时改为 false，并填：
#   # GITHUB_APP_ID=...
#   # GITHUB_APP_PRIVATE_KEY="-----BEGIN...-----"  # 或 GITHUB_APP_PRIVATE_KEY_PATH
#   OPENAI_API_KEY=   # 可选

docker compose -f deploy/docker-compose.yml --env-file .env up --build
```

健康检查与控制台：

- API：http://localhost:8000/health
- 安装说明：http://localhost:8000/
- **控制台**：http://localhost:8000/console

未设置 `ADMIN_TOKEN` 时，`GET /jobs` / `POST /jobs/{id}/retry` 返回 **503**。

### 无真 App 快速验收

```bash
# .env 保持 USE_FIXTURES=true，GITHUB_WEBHOOK_SECRET 与下方一致（compose 默认 dev-secret）
python scripts/smoke_fixtures_webhook.py
# 期望：HTTP 202 → 打开 http://localhost:8000/console 可见 Postgres jobs 行
```

## 4. smee 转发到本地（可选 · 真 App）

```bash
npx smee -u https://smee.io/YOUR_CHANNEL -t http://127.0.0.1:8000/webhooks/github
```

即使用 smee，也应对 body 做 HMAC（保持 `WEBHOOK_SKIP_VERIFY=false`）。

## 5. 开 PR / 发 webhook 验证

1. 真 App：在测试仓开一个 PR（或 push 触发 `synchronize`）；或本地跑 `scripts/smoke_fixtures_webhook.py`
2. API 应尽快 `202`，**Postgres `jobs` 表**写入任务行（控制台 / `GET /jobs` 同源；Redis **只**做 delivery 去重 + arq，**不再**写 `pr-sentinel:jobs` LIST）
3. Worker 跑规则（+可选 LLM）；真 App 时在 PR 下写/更新 sticky comment；fixtures 模式不打真网
4. 打开 http://localhost:8000/console ：
   - 看到最近任务（queued → running → success / failed）
   - 在控制台填入 `ADMIN_TOKEN` 保存 Cookie
   - 失败任务点 **重试**（等价于 `POST /jobs/{id}/retry`）

API 示例：

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/jobs | jq
curl -s -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://127.0.0.1:8000/jobs/<job-or-delivery-id>/retry
```

## 6. 仓库配置（可选）

在 **default branch** 放 `.pr-sentinel.yml`（PR 分支上的配置会被忽略）。示例见仓库根 `.pr-sentinel.yml.example`。

## 常见问题

| 现象 | 排查 |
| --- | --- |
| 401 invalid signature | Secret 与 `GITHUB_WEBHOOK_SECRET` 不一致，或 body 被中间层改写 |
| 控制台无任务 | 确认 webhook 到了 API、delivery 未重复；看 api 日志 `record_job`；确认 Postgres `jobs` 表有行 |
| 重试 503 | 未设置 `ADMIN_TOKEN` |
| 重试 403 | Token 错误；可用 `Authorization: Bearer` 或 `X-Admin-Token` |
| 无 PR 评论 | Worker 日志、安装权限、`USE_FIXTURES`、installation_id（fixtures 模式本就不会发真评论） |
| Worker 启动报 Live mode / missing credentials | `USE_FIXTURES=false` 时必须配置 App 或 `GITHUB_TOKEN`（M18 不再静默 fixtures） |
