# 端到端演示（M4 / M19 / M34）

两条路径：

1. **默认验收（无真 App）**：`USE_FIXTURES=true` + 本地 HMAC webhook → `202` → `/console` 从 **Postgres** 看到 job（见 README「无真 App smoke」与 `scripts/smoke_fixtures_webhook.py`）。
2. **可选真 App**：GitHub App → smee 转发 → 安装到测试仓 → 开 PR → 看控制台、Check Run、sticky / inline 评论（下文）。

## 前置

- Docker / Compose，或本机 Redis + Postgres + Python 3.11+
- 真 App 路径额外需要：Node（`npx smee`）、有管理权限的测试仓库

---

## 可选真 App

### 1. 创建 GitHub App

1. GitHub → **Settings → Developer settings → GitHub Apps → New GitHub App**
2. **Webhook URL**：先去 [smee.io](https://smee.io/) 新建 channel，把 URL 填到 App Webhook（或公网 `https://<host>/webhooks/github`）
3. **Webhook secret**：自拟长随机串，稍后写入 `.env` 的 `GITHUB_WEBHOOK_SECRET`
4. **Repository permissions**（缺一项都会在对应出站 API 上 403）：

   | Permission | Access | 用途 |
   | --- | --- | --- |
   | **Checks** | **Read & write** | 创建 / 更新 Check Run `pr-sentinel`（缺则常见 **403**） |
   | Contents | Read | 读 PR 文件 / 默认分支配置 |
   | Pull requests | Read & write | 读 PR、发 / 更新 sticky 与 inline review 评论 |
   | Issues | Read & write | sticky 走 issue comments API |

5. Subscribe to events：至少勾选 **Pull request**
6. 创建后记下 **App ID**，生成并下载 **Private key**（PEM）

安装页（`http://localhost:8000/`）与上表一致；改权限后需在 App 安装页对仓库 **Accept** 新权限。

### 2. 安装 App 到测试仓

App 页 → **Install App** → 选择测试组织/用户 → 仅选测试仓库 → Install。

记下安装后的 **installation id**（安装页 URL 或后续真实 webhook payload 的 `installation.id`）。**不要**用手写 / smoke 假 ID 做 live。

### 3. PEM 两路径（对照 `deploy/docker-compose.yml` 注释）

二选一即可（`packages/common/settings.py`：`GITHUB_APP_PRIVATE_KEY` 或可读的 `GITHUB_APP_PRIVATE_KEY_PATH`）。

**路径 A — 环境变量多行 PEM**

```bash
# .env（引号内保留换行；也可用字面 \n，视 shell/compose 解析而定）
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----
MIIE...
-----END RSA PRIVATE KEY-----"
# 不要同时依赖错误的 PATH
```

**路径 B — 文件路径 + Compose 挂载**（推荐容器）

与 `deploy/docker-compose.yml` 中 api/worker 注释一致：

```bash
# .env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem
GITHUB_APP_PEM_HOST_PATH=./app.pem   # 仅给 compose 变量替换用
```

在 compose 的 `api` / `worker` 取消注释 volumes：

```yaml
# volumes:
#   - ${GITHUB_APP_PEM_HOST_PATH}:/secrets/github-app.pem:ro
```

并保证容器内 `GITHUB_APP_PRIVATE_KEY_PATH=/secrets/github-app.pem`。本机非 compose 时可直接 `GITHUB_APP_PRIVATE_KEY_PATH=/absolute/path/to/app.pem`。

### 4. 启动 PR Sentinel

```bash
cp .env.example .env
# 编辑 .env：
#   GITHUB_WEBHOOK_SECRET=<与 App Webhook Secret 相同>
#   ADMIN_TOKEN=<控制台鉴权用长随机串>
#   USE_FIXTURES=false
#   GITHUB_APP_ID=...
#   GITHUB_APP_PRIVATE_KEY=...   # 或 GITHUB_APP_PRIVATE_KEY_PATH + 挂载
#   WEBHOOK_SKIP_VERIFY=false
#   OPENAI_API_KEY=   # 可选

docker compose -f deploy/docker-compose.yml --env-file .env up --build
```

健康检查与控制台：

- API：http://localhost:8000/health
- 安装说明：http://localhost:8000/
- **控制台**：http://localhost:8000/console

未设置 `ADMIN_TOKEN` 时，`GET /jobs` / `POST /jobs/{id}/retry` 返回 **503**。

### 5. `installation_id`（必须来自真实 App webhook）

Worker 用 webhook 写入 job 的 `installation_id` 换 installation token（见 `extract_job_payload` → `payload.installation.id`）。

| 来源 | 可否用于 live |
| --- | --- |
| 真实 GitHub App 投递的 `pull_request` webhook 里的 `installation.id` | ✅ |
| App 安装页 / API 查到的、且与该仓库安装一致的 id | ✅（仍建议以 webhook 为准写入 job） |
| `scripts/smoke_fixtures_webhook.py` 或 fixtures JSON 里的**假** id | ❌ 不可 live；假 id 换 token / 调 API 会失败 |

无真 App 默认验收保持 `USE_FIXTURES=true`，不要指望 smoke 假 payload 写出站评论或 Check Run。

### 6. HMAC + smee

API 对 `POST /webhooks/github` 的处理顺序（与代码一致）：

1. **限流** → 超限 **429**
2. **体长**（Content-Length / body）→ 超限 **413**
3. **HMAC**（`X-Hub-Signature-256` vs `GITHUB_WEBHOOK_SECRET`）→ 失败 **401**；仅当 `WEBHOOK_SKIP_VERIFY=true`（或 `ALLOW_INSECURE_WEBHOOKS`）时跳过

即使用 smee 转发，也应对 **原始 body** 验签，保持 `WEBHOOK_SKIP_VERIFY=false`。

```bash
npx smee -u https://smee.io/YOUR_CHANNEL -t http://127.0.0.1:8000/webhooks/github
```

**`WEBHOOK_SKIP_VERIFY=true` 风险**：任意人可向公网 / 已知 smee URL 伪造 webhook；仅限本机无假 body 的纯 curl 调试，**生产与公开 smee 禁止**。

常见失败：

| 现象 | 排查 |
| --- | --- |
| 401 invalid signature | Secret 与 App / `.env` 不一致；smee/代理改写了 body；用了错误的签名头 |
| 429 | 触发 M24 限流，稍后再试或调 `WEBHOOK_RATE_*` |
| 413 | body / Content-Length 超过 `WEBHOOK_MAX_BODY_BYTES`（默认 1MiB） |
| smee 有事件但 API 无日志 | 目标 URL 是否 `http://127.0.0.1:8000/webhooks/github`；compose 端口映射 |

### 7. 开 PR 验证

1. 在已安装 App 的测试仓开 PR（或 `synchronize`）
2. API 应尽快 `202`，**Postgres `jobs`** 落库（控制台 / `GET /jobs`）；Redis **只**做 delivery 去重 + arq
3. Worker：规则（+可选 LLM）→ Check Run + sticky / inline（视配置）
4. 打开 http://localhost:8000/console ：queued → running → success / failed；失败可重试

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/jobs | jq
curl -s -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  http://127.0.0.1:8000/jobs/<job-or-delivery-id>/retry
```

### 8. 仓库配置（可选）

在 **default branch** 放 `.pr-sentinel.yml`（PR 分支上的配置会被忽略）。示例见仓库根 `.pr-sentinel.yml.example`。

---

## 无真 App 快速验收

```bash
# .env 保持 USE_FIXTURES=true，GITHUB_WEBHOOK_SECRET 与下方一致（compose 默认 dev-secret）
python scripts/smoke_fixtures_webhook.py
# 期望：HTTP 202 → 打开 http://localhost:8000/console 可见 Postgres jobs 行
```

---

## Live 预检（M35）

开真实 PR / 打真网之前，先跑本地静态预检（**不**调 GitHub API、**不**签发 JWT）：

```bash
# 建议先准备 .env（USE_FIXTURES=false + App 或 PAT），或 export 同名变量
python scripts/preflight_live.py
# 可选：PREFLIGHT_HEALTH_URL=http://127.0.0.1:8000/health
#       PREFLIGHT_SKIP_HEALTH=1
```

- **exit 0**：无 FAIL（允许 WARN，例如 API 未启动时 `/health` 不通）
- **exit 1**：配置未就绪（如仍 `USE_FIXTURES=true`、缺 App/PAT、PEM 路径不可读）

通过后再按上文启动 compose / smee 并开 PR。

## Live FAQ（`USE_FIXTURES=false`）

| 现象 | 说明 / 排查 |
| --- | --- |
| Worker / `build_client` 启动即报 Live mode / missing credentials | M18 **fail-fast**：必须配置 App（`GITHUB_APP_ID` + PEM 或 PATH）或 `GITHUB_TOKEN`，**不会**再静默回落 fixtures |
| Check Run **403** | App 缺 **Checks: Read & write**，或安装后未 Accept 新权限 |
| 无 sticky / inline 评论 | 缺 Pull requests / Issues 写权限；或 `summary_comment=false` / `inline_comments=false`；或 `installation_id` 无效 |
| job 有 findings 但 GitHub 无动静 | 确认 `USE_FIXTURES=false` 且凭据有效；看 worker 日志出站错误 |
| 控制台无任务 | webhook 未到 API、delivery 重复、或 Postgres 未写入；看 api 日志 `record_job` |
| 重试 503 / 403 | 未设 / 错误的 `ADMIN_TOKEN` |

## 其他常见问题

| 现象 | 排查 |
| --- | --- |
| 401 invalid signature | 见上文 HMAC + smee |
| 重试 503 | 未设置 `ADMIN_TOKEN` |
| 重试 403 | Token 错误；可用 `Authorization: Bearer` 或 `X-Admin-Token` |
