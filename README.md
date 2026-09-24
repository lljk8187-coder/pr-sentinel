# PR Sentinel

GitHub PR 质量闸门 — **1.6.0 / Phase11**：真 App live e2e **已于 2026-09-24 证明**（证据见 [docs/records/2026-09-24-phase11-live-e2e.md](./docs/records/2026-09-24-phase11-live-e2e.md)）；对他人仍 **可选**（非硬门禁）。Phase10（1.5.0）：golden 抽样与 score。Phase9（1.4.0）：真 App 就绪文档。Phase8（1.3.0）：输出与控制台。Phase7（1.2.0）：分析质量。Phase6（1.1.0）：webhook 限流/体长 / 嵌套配置 / TestClient 消噪。Phase5（1.0.0）：live fail-fast / smoke 脚手架 / console ops。Phase4（0.10.0）：出站脱敏 / Worker 韧性 / compose health。

> 本阶段 **不做** 完整 SaaS 多租户 / Alembic / ORM；Redis **不**再存 jobs（仅 delivery 去重 + arq）。

## 架构（Phase2）

```
GitHub / smee.io ──► apps/api (FastAPI)
                        │ HMAC-SHA256 (X-Hub-Signature-256)
                        │ Redis SET NX 去重 X-GitHub-Delivery
                        │ arq.enqueue_job("process_pr")
                        │ record_job → Postgres jobs 表（控制台 / 重试）
                        ▼ 尽快 202
                     Redis (arq + delivery dedup) · Postgres (jobs)
                        │
                        ▼
                  apps/worker (arq)
                        │ 更新 PG job status/error/arq_job_id
                        │ 成功时写回 findings / report_md / check_run_id
                        └─► Check Run (pr-sentinel) + sticky PR comment + high-severity inline comments

浏览器 ──► / 安装说明 · /console 任务列表 · /console/jobs/{id} 详情（报告 + findings）
         GET /jobs · GET /jobs/{id} · POST /jobs/{id}/retry（ADMIN_TOKEN，读 PG）
```

## 目录

```
apps/api/                 FastAPI：webhook + /console + /jobs
apps/api/templates/       中文控制台 / 安装页（Jinja2）
apps/worker/              arq WorkerSettings + process_pr
packages/common/          settings / queue / job_store(asyncpg) / DEFAULT_CONFIG
packages/github/          GitHub 客户端 + 规则 + llm + sticky
sql/001_jobs.sql          Postgres jobs 表（compose initdb）
docs/e2e-demo.md          端到端演示（含可选真 App；默认无真 App）
docs/records/             可选 live 联调证据模板（M36）
scripts/smoke_fixtures_webhook.py  无真 App HMAC webhook smoke（stdlib）
scripts/preflight_live.py         live 预检（stdlib；不调 GitHub API）
deploy/docker-compose.yml
tests/
```

## 控制台

| URL | 说明 |
| --- | --- |
| http://localhost:8000/ | 安装 / 配置说明（App、smee、环境变量） |
| http://localhost:8000/console | 最近任务列表 + 失败重试 |
| http://localhost:8000/console/jobs/{id} | 任务详情（状态 / 报告 / findings） |
| http://localhost:8000/health | 健康检查 |
| `GET /jobs` | JSON 任务列表（需鉴权） |
| `GET /jobs/{id}` | JSON 任务详情（含 findings / report_md / check_run_id / **check_run_url**） |
| `GET /metrics` | 进程内计数 JSON（webhook accepted/duplicate、worker success/fail；需 ADMIN_TOKEN，同 `/jobs`） |
| `POST /jobs/{id}/retry` | 按 job id 或 delivery_id 重放入队 |

鉴权：环境变量 `ADMIN_TOKEN`；请求头 `Authorization: Bearer <token>` 或 `X-Admin-Token`。  
**未配置 `ADMIN_TOKEN` 时**，jobs 读写接口返回 **503**（见 [`.env.example`](./.env.example)）。

完整联调步骤：[docs/e2e-demo.md](./docs/e2e-demo.md)。

## 配置（`.pr-sentinel.yml`）

- Worker **只读 default branch** 上的 `.pr-sentinel.yml`（PR 分支上的配置忽略）。
- 合并策略：`deep_merge(DEFAULT_CONFIG, repo_yml)`；加载后手写 `validate_config` 校验未知键 / 类型 / 枚举，坏字段回退默认值并追加中文 notes（**不**因非法值失败整 job；解析失败仍仅用 DEFAULT）。
- **list 为整表替换**：`deep_merge` 对 list / 标量是 overlay **整段替换**（不是追加）。因此若只想少忽略几条路径，须在配置里写出**完整** `ignore_paths` 列表；`ignore_paths: []` 表示不过滤（空表替换默认，不会保留默认的 `docs/**` / `**/*.md`）。
- 文件不存在 / 解析失败 → 仅用 `DEFAULT_CONFIG`，并在报告中注明。
- Fixture 模式：读 `tests/fixtures/pr-sentinel.yml`。
- **落库脱敏**：`privacy.redact_secrets`（默认 true）时，Worker 在写入 Postgres 的 findings（含 `meta.match`）与 `report_md` 前做 `***REDACTED***` 替换。

示例见 [`examples/.pr-sentinel.yml`](./examples/.pr-sentinel.yml) / [`.pr-sentinel.yml.example`](./.pr-sentinel.yml.example)。

关键字段：

| 字段 | 说明 |
| --- | --- |
| `check_run` | 是否创建 GitHub Check Run `pr-sentinel`（默认 `true`）；无 error/high/critical → success，否则 failure |
| `inline_comments` | 高危（error/high/critical）且有 path+line 时发 inline review comment（默认 `true`） |
| `update_strategy` | `update`（默认 PATCH）/ `recreate`（删旧再 POST）/ `skip_if_exists` |
| `ignore_paths` | gitignore 风格（**pathspec** `GitIgnoreSpec` / gitwildmatch）：`**`、目录前缀、取反 `!`。默认 `docs/**` 与 `**/*.md`。规则引擎与 LLM **共用**同一套过滤（`filter_ignored` 后再分析）。**不读** 仓库 `.gitignore`。配置 list 为整表替换；`[]` = 不过滤。因此默认情况下 **md 内密钥扫不到**（被 `**/*.md` 忽略）。 |
| `rules.secrets` | patch/文件名正则 |
| `rules.large_files` | `max_bytes`（patch 字节）、`max_additions`、`binary_extensions`；无 patch 且高 changes/二进制扩展 → `binary_or_truncated`（不臆造真实 size） |
| `rules.weakened_tests` | 删除测试文件或 assert 净减少 |
| `privacy.redact_secrets` | 送入 LLM 前 redact；成功落库前也对 findings/`report_md`（含 `meta.match`）脱敏（`***REDACTED***`，默认 true） |
| `llm.enabled` | 是否启用 LLM（仍需 API Key） |
| `llm.max_patch_chars` | 送入 LLM 的 patch 截断长度（默认 12000） |
| `llm.temperature` | 默认 `0.2` |
| `analyzer.mode` | `rules` / `rules+llm`（默认）/ `fake`；无密钥时 `rules+llm` 自动降级 |
| `diff.max_*` | 分页与截断；截断时报告正文声明 **Limits 截断** |

## LLM（OpenAI 兼容）

环境变量（见 [`.env.example`](./.env.example)）：

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` 或 `PR_SENTINEL_OPENAI_API_KEY` | API Key；后者优先 |
| `OPENAI_BASE_URL` | 可选，默认 `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 可选，默认 `gpt-4o-mini` |

行为：

- 使用 **httpx** `POST {BASE}/chat/completions`（不强依赖 openai SDK）。
- **无密钥**：跳过 LLM；报告 `Assumptions` 标明 `llm_skipped: true` 与原因；规则引擎照常跑。
- 输入：变更摘要（文件列表 + 规则 findings）+ **截断后的 patch**；若 `privacy.redact_secrets=true` 则先 redact。
- 瞬态错误（超时 / 网络 / 5xx / 429）→ 异常冒泡，arq `Retry` 退避（`max_tries=3`）。
- 明确 4xx（如 401）→ 软跳过 LLM（写入 assumptions），不无限重试。

报告 Markdown 含：总览与 **severity**、规则发现、LLM 发现（或 skipped）、assumptions、Limits 截断声明。Finding：`{source: rules|llm, severity, title, detail, path?}`。

## 认证

| 场景 | 方式 |
| --- | --- |
| **生产** | GitHub App：`GITHUB_APP_ID` + private key + webhook `installation.id` → JWT → installation token |
| **本地 / 兜底** | `GITHUB_TOKEN`（PAT / fine-grained） |
| **无凭据演示** | `USE_FIXTURES=true` 读 `tests/fixtures/`，不打真网 |
| **Live 无凭据** | `USE_FIXTURES=false` 且 App/PAT 皆空 → **启动 / build_client 立即失败**（不再静默回落 fixtures） |
| **控制台 API** | `ADMIN_TOKEN` + Bearer / `X-Admin-Token` |

真 App 步骤（**Checks: Read & write**、PEM 两路径、`installation_id`、HMAC/smee FAQ）：[docs/e2e-demo.md](./docs/e2e-demo.md#可选真-app)。
无 Docker daemon 时用 **Host-mode live**（本机 Redis/Postgres + uvicorn/arq）：[docs/e2e-demo.md §4b](./docs/e2e-demo.md#4b-host-mode-live无-docker-daemon--对照-phase11)。
开 PR 前可跑 live 预检：`python scripts/preflight_live.py`（exit 0=无 FAIL；详见 [docs/e2e-demo.md](./docs/e2e-demo.md#live-预检m35)）。
联调证据模板（可选落盘）：[docs/records/](./docs/records/)。

## 本地 Webhook：smee + HMAC

即使用 [smee.io](https://smee.io/) 转发，也应对 body 做 HMAC（与 GitHub 生产一致）。

1. 在 smee.io 新建 channel，记下 URL。  
2. GitHub App / repo webhook：Payload URL = smee URL；Secret = 与本地 `GITHUB_WEBHOOK_SECRET` **相同**。  
3. 本地转发：

```bash
npx smee -u https://smee.io/YOUR_CHANNEL -t http://127.0.0.1:8000/webhooks/github
```

4. `.env`：

```bash
GITHUB_WEBHOOK_SECRET=与 GitHub Webhook Secret 一致
WEBHOOK_SKIP_VERIFY=false   # 本地也建议保持验签
ADMIN_TOKEN=足够长的随机串
```

仅在完全没有 Secret 的纯 curl 调试时才设 `WEBHOOK_SKIP_VERIFY=true`。

## 快速开始

### 安装

```bash
cd pr-sentinel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 填入 ADMIN_TOKEN；可选 OPENAI_API_KEY
```

### Docker Compose

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up --build
curl http://localhost:8000/health
open http://localhost:8000/console
```

服务：`api`（:8000，含控制台）+ `worker`（arq）+ `redis`（队列/去重）+ `postgres`（**M5 jobs 存档**，挂载 `sql/` → initdb）。`api`/`worker` 设 `restart: unless-stopped`；worker 用进程级 healthcheck（查 PID1 为 `apps/worker/main.py` / arq，无 HTTP）。必填环境变量见 [`.env.example`](./.env.example)。

端到端演示：[docs/e2e-demo.md](./docs/e2e-demo.md)。

### 无真 App smoke（默认验收 · M19）

不创建 GitHub App、不用 smee。目标：HMAC 验签通过 → API **202** → **Postgres** `jobs` 落库 → `/console` 可见。

```bash
# 1) .env（或 compose 默认）
#   USE_FIXTURES=true
#   GITHUB_WEBHOOK_SECRET=dev-secret   # 与下方一致
#   ADMIN_TOKEN=dev-admin              # 控制台 /jobs 鉴权
#   WEBHOOK_SKIP_VERIFY=false

docker compose -f deploy/docker-compose.yml --env-file .env up --build -d
curl -sf http://127.0.0.1:8000/health

# 2) 发一条签名 webhook（stdlib，零新依赖）
export GITHUB_WEBHOOK_SECRET=dev-secret
python scripts/smoke_fixtures_webhook.py
# 期望打印 HTTP 202

# 3) 控制台 / API 应能看到 PG 任务
open http://127.0.0.1:8000/console
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" http://127.0.0.1:8000/jobs | jq
```

说明：Redis 只做 delivery 去重 + arq；**jobs 只在 Postgres**。真 App + smee 仍见下文「本地 Webhook」与 [docs/e2e-demo.md](./docs/e2e-demo.md)（可选）。

### 本地分进程

真 App live 且无 Docker daemon 时，把下方 `USE_FIXTURES=true` 换成 live 配置，完整步骤见 [Host-mode live](./docs/e2e-demo.md#4b-host-mode-live无-docker-daemon--对照-phase11)。

```bash
# 终端 1 — Redis + Postgres（或只用 compose 起依赖）
redis-server
# docker run --rm -e POSTGRES_USER=prsentinel -e POSTGRES_PASSWORD=prsentinel \
#   -e POSTGRES_DB=prsentinel -p 5432:5432 -v "$PWD/sql:/docker-entrypoint-initdb.d:ro" \
#   postgres:16-alpine

# 终端 2 — API
export PYTHONPATH=.:packages:packages/github:apps/api
export USE_FIXTURES=true
export ADMIN_TOKEN=dev-admin
export DATABASE_URL=postgresql://prsentinel:prsentinel@localhost:5432/prsentinel
uvicorn main:app --app-dir apps/api --reload --port 8000

# 终端 3 — arq Worker
export PYTHONPATH=.:packages:packages/github:apps/worker
export USE_FIXTURES=true
export DATABASE_URL=postgresql://prsentinel:prsentinel@localhost:5432/prsentinel
python apps/worker/main.py
```

## Sticky Comment 幂等

Marker（按 PR 稳定，**不**随 `head_sha` 变）：

```text
<!-- pr-sentinel:summary:{owner}/{repo}:{pr_number} -->
```

- `update`：已有 marker → `PATCH`；否则 `POST`。
- `recreate`：删旧再 `POST`。
- `skip_if_exists`：已有 marker 则跳过。

重复跑 `process_pr` 只会 sticky update，不刷屏。

## Diff 拉取

`GET /repos/{owner}/{repo}/pulls/{n}/files`，分页 + 截断：

- `DIFF_MAX_PAGES` / config `diff.max_pages`（默认 5）
- `DIFF_PER_PAGE` / `diff.per_page`（默认 100）
- `DIFF_MAX_FILES` / `diff.max_files`（默认 300）

截断时报告中标注 **Limits 截断声明**。

## Worker 重试（M3）

`WorkerSettings`：`max_tries=3`、`job_timeout=300`、瞬态错误 `Retry(defer=…)` 退避。业务 skip（如 `summary_comment=false`）正常返回，不耗尽重试。

控制台 **失败重试**（M4/M5）会重新 `enqueue process_pr`，payload 从 **Postgres jobs** 存档读取。

## Phase2 M5：Jobs → Postgres

- 表定义：[`sql/001_jobs.sql`](./sql/001_jobs.sql)（`id UUID`、`delivery_id UNIQUE`、`payload/findings JSONB` 等）。
- `packages/common/job_store.py` 使用 **asyncpg**；`DATABASE_URL` 见 [`.env.example`](./.env.example)。
- Redis **仅**保留 delivery 去重 + arq；**禁止**再写 `pr-sentinel:job:*`。
- 不做多租户 / Alembic / ORM；不用 PG 替 arq。

## Phase2 M6：ignore_paths + large_files（语义见 Phase7 M28）

- `ignore_paths`：使用 **pathspec** 的 `GitIgnoreSpec`（gitwildmatch），覆盖目录前缀、`**`、取反 `!`。
- **默认**：`docs/**` 与 `**/*.md`（见 `DEFAULT_CONFIG`）。
- **共用过滤**：规则引擎与 LLM 都先 `filter_ignored`，只对 kept 文件分析（LLM 收到的也是 kept）。
- **不读** 仓库 `.gitignore`（仅认配置 / 默认里的 `ignore_paths`）。
- **list 整表替换**：`deep_merge` 对 list 是 overlay 替换不是追加；只想少忽略时须显式写完整列表；`ignore_paths: []` = 不过滤。
- **默认后果**：`README.md` / 任意 `*.md` 内的密钥等默认**扫不到**（被 `**/*.md` 忽略）；若要扫 md，设完整列表或 `ignore_paths: []`。
- `large_files`：patch 字节 ≥ `max_bytes`、additions ≥ `max_additions`、或无 patch 且（高 changes / 命中 `binary_extensions`）→ finding；meta 含 `reason` / `approx_patch_bytes` / `additions` / `binary_or_truncated`。
- **不做** Contents API 拉文件、不臆造真实文件 size；小文本不误报；**不做** 自动合并仓库 `.gitignore`。
- 依赖：`pathspec`（见 `requirements.txt` / `pyproject.toml`）。

## Phase2 M7：GitHub Actions CI

- Workflow：`.github/workflows/ci.yml`（`push`/`pull_request` → `main`）。
- Job `test`：`ubuntu-24.04` + Python 3.11 + Postgres 16 service；`actions/checkout@v7` / `setup-python@v7`；应用 `sql/001_jobs.sql` 后 `pytest -q`。
- Redis 不作为 CI service（fakeredis）。


## Phase2 M8：Check Run annotations + 高危 inline comments

- 分析完成后创建/更新名为 `pr-sentinel` 的 GitHub Check Run：`in_progress` → `completed`。
- **Conclusion**：findings 中**没有** severity ∈ {error, high, critical} → `success`，否则 `failure`。
- **Annotations**：带 path+line 的 findings 写入 Check Run `output.annotations`（每请求最多 50 条；超出截断并在 summary 中注明）。
- **Inline comments**：仅对高危（high|critical|error）且有 path+line 的 findings；无 line 只进 Check Run/sticky，不臆造行号。
- `summary_comment=false` 时跳过 sticky，但仍写 Check Run（除非 `check_run=false`）。
- 默认：`check_run: true`、`inline_comments: true`。

## Phase3 M11：Inline RIGHT 行号 + fingerprint upsert

- Inline review comment 使用新文件 **RIGHT** 1-based `line` + `side=RIGHT`（不用 `position`）。
- 无行号 / 删除行 / 二进制无 patch / 臆造不在 RIGHT patch 中的行 → **跳过** POST，避免 GitHub 422 拖垮整 job。
- Body 首行 fingerprint：`<!-- pr-sentinel:inline:{path}:{line}:{rule_id} -->`；synchronize 时同 fingerprint → PATCH body（或内容未变则 skip），不盲 POST 重复。
- Worker 把 PR files/patch 传入 `publish_inline_comments` 做 `line_in_patch_right` 校验。

## Phase2 M9：Job detail + findings 写回

- Worker 成功后把 `findings`（`Finding.to_dict()`）、`report_md`、`check_run_id` 写入 Postgres `jobs`（`update_job_status` / `update_job_result` / `update_job_status_by_payload` 可选字段；仅当非 `None` 时 SET）。
- 失败（非 Retry）仍只写 `status` + `error`。
- `GET /jobs/{id}`：与列表相同的 ADMIN_TOKEN 鉴权（未配置 503 / 错 token 403）；缺失 404；返回 findings / report_md / check_run_id 等，**不**默认 dump 完整 payload。
- 控制台：列表行链接到 `/console/jobs/{id}`；详情页展示状态/错误、Markdown 报告、findings 表与重试；文案改为任务列表来自 **Postgres**。

## Phase3 M13：ops 收尾

- **check_run_url**：由 `owner`/`repo`/`check_run_id` 计算为 `https://github.com/{owner}/{repo}/runs/{id}`（UI 路径，**不是** API 的 `/check-runs/`）；`GET /jobs/{id}` 与控制台详情共用 `job_to_detail_dict`，不落库 html_url。
- **结构化日志**：webhook 入队/去重与 worker `process_pr` 状态转换日志带可检索字段 `delivery_id` / `job_id` / `sha`（短 12 位）。
- **指标**：`/console` 按当前列表任务的 `status` 聚合计数；可选 `GET /metrics` 返回进程内计数（无 prometheus）。


## Phase6（1.1.0）：硬化与发布

- **M22**：pytest `filterwarnings` 消 Starlette TestClient / anyio BlockingPortal 弃用警告（保留同步 TestClient）。
- **M23**：`validate_config` 嵌套 walk 剥未知键 + 路径 note（仍 soft）。
- **M24**：webhook Content-Length/body 超限 → 413（默认 1MiB）；Redis INCR+EXPIRE 限流 → 429（默认 120/60s）；顺序限流→体长→HMAC；无 slowapi。
- **M25**：版本对齐 **1.1.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.1`。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.1.0 硬门禁。

## Phase11（1.6.0）：真 App live e2e 证明

- **Live proof**：2026-09-24（Asia/Shanghai）真实 GitHub App `pr-sentinel-live-e2e` 全链路成功 — smee → HMAC webhook → host Redis/Postgres/uvicorn/arq → Check Run + sticky + inline（rules secrets）；详见 [docs/records/2026-09-24-phase11-live-e2e.md](./docs/records/2026-09-24-phase11-live-e2e.md)。
- **版本对齐**：**1.6.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.6`（子包 `pr-sentinel-github` 仍 0.2.0；smoke UA `pr-sentinel-smoke/0.1` 未动）。
- **Notes**：真 App / live E2E 对他人仍 **可选**，不是开发或 CI 硬门禁；默认继续用 fixtures smoke。

## Phase10（1.5.0）：golden 抽样与 score

- **M38**：`tests/golden/` 目录 + `load_case` + README 契约 + 烟测。
- **M39**：五类规则各 ≥1 正例 / 反例 JSON + 参数化 `test_golden_rules.py`。
- **M40**：LLM 解析 golden（valid / soft / empty / fenced）+ `test_golden_llm.py`（无真 OpenAI）。
- **M41**：`scripts/golden_score.py` 打印 must_hit recall / must_not FP / soft_ok（默认不因分数非零退出）；版本对齐 **1.5.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.5`（子包 `pr-sentinel-github` 仍 0.2.0；smoke UA `pr-sentinel-smoke/0.1` 未动）。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.5.0 硬门禁。

## Phase9（1.4.0）：真 App 就绪文档

- **M34**：真 App 文档补全 — **Checks: Read & write**、Contents/PR/Issues、PEM 两路径、真实 `installation_id`、HMAC/smee FAQ；`install.html` + README 短链。
- **M35**：`scripts/preflight_live.py` — live 静态预检（stdlib；不调 GitHub API / 不签发 JWT）。
- **M36**：`docs/records/` — 联调证据 TEMPLATE + 脱敏与 gitignore 约定。
- **M37**：版本对齐 **1.4.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.4`（子包 `pr-sentinel-github` 仍 0.2.0；smoke UA `pr-sentinel-smoke/0.1` 未动）。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.4.0 硬门禁。

## Phase8（1.3.0）：输出与控制台

- **M30**：`merge_findings` — 同 path+line 跨源保留更高 severity 并记 `meta.sources`；同源同键只留一条；接入 `RulesLLMAnalyzer`。
- **M31**：sticky 正文硬上限约 60000（`<!-- pr-sentinel:truncated -->`）；报告段内 severity 排序；inline detail 约 2k 截断。
- **M32**：控制台 job 详情 findings 表增加 `source` / `rule_id` 列（缺则回退 meta）。
- **M33**：版本对齐 **1.3.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.3`（子包 `pr-sentinel-github` 仍 0.2.0；smoke UA `pr-sentinel-smoke/0.1` 未动）。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.3.0 硬门禁。

## Phase7（1.2.0）：分析质量与发布

- **M26**：规则 `skipped_tests` + `dangerous_commands`；secrets 默认模式加 `ghp_` / `sk-`。
- **M27**：`llm_parse_soft` — LLM 无法解析为结构化 findings 时降级忽略；去掉合成 info Finding。
- **M28**：`ignore_paths` 文档边界（pathspec GitIgnoreSpec、默认 `docs/**` + `**/*.md`、规则+LLM 共用 `filter_ignored`、**不读** `.gitignore`、list 整表替换与 `[]` 不过滤）；契约测 `ignore_paths: []` 时 md 进 kept 可被 secrets 扫到。默认过滤逻辑不变。
- **M29**：版本对齐 **1.2.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.2`（子包 `pr-sentinel-github` 仍 0.2.0；smoke UA `pr-sentinel-smoke/0.1` 未动）。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.2.0 硬门禁。

## Phase5（1.0.0）：就绪发布

- **M18**：`USE_FIXTURES=false` 时缺 App/PAT 凭证 **fail-fast**（不再静默回落 fixtures）。
- **M19**：无真 App smoke 脚手架 — e2e 文档修正（jobs → Postgres）；可选 `scripts/smoke_fixtures_webhook.py`；Compose PEM path 核对。
- **M20**：控制台 ops UX — failed 行高亮、error 截断、`?status=` 过滤。
- **M21**：版本对齐 **1.0.0** + [CHANGELOG.md](./CHANGELOG.md)；User-Agent `pr-sentinel/1.0`。
- **Notes**：真 GitHub App / live E2E **可选**，不是 1.0.0 硬门禁。

## Phase4（0.10.0）：发布卫生

- **M14**：`privacy.redact_secrets` 时，出站前对 findings / report 脱敏，再发 Check Run / sticky / inline（与落库一致）。
- **M16**：Worker 瞬态错误在最后一次 `job_try` 写入 `status=failed`（不再卡在 `running`）；中间尝试仍走 arq `Retry`。
- **M15**：compose `api`/`worker` `restart: unless-stopped`；worker 进程级 healthcheck；`.env.example` 标注必填 Settings 变量。
- **M17**：版本对齐 **0.10.0** + [CHANGELOG.md](./CHANGELOG.md)。

## 测试

需要可达的 Postgres（与 `DATABASE_URL` 一致；默认 `postgresql://prsentinel:prsentinel@localhost:5432/prsentinel`）。
Redis 用 **fakeredis**，本地/CI **不**依赖 Redis service。

```bash
pip install -r requirements.txt
# 可选：先应用 schema（conftest 也会 execute sql/001_jobs.sql）
# psql "$DATABASE_URL" -f sql/001_jobs.sql
pytest -q
```

## CI（M7）

[![CI](https://github.com/lljk8187-coder/pr-sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/lljk8187-coder/pr-sentinel/actions/workflows/ci.yml)

Push / PR 到 `main` 时，[`.github/workflows/ci.yml`](./.github/workflows/ci.yml) 在 `ubuntu-24.04` + Python 3.11 上跑：

- **Postgres 16** service（`prsentinel` / `prsentinel` / `prsentinel`，健康检查后注入 `DATABASE_URL`）
- `pip install -r requirements.txt` → 用 asyncpg 应用 `sql/001_jobs.sql` → `pytest -q`
- 不启 Redis service（测试侧 fakeredis）

## 许可

MIT — 见 [LICENSE](./LICENSE)。
