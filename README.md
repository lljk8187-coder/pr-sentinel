# PR Sentinel

GitHub PR 质量闸门 — **M2**：Webhook HMAC 验签 → Delivery 去重 → **arq** 入队 → Worker 读 **default branch** `.pr-sentinel.yml` → 拉 diff → **规则引擎** → **Sticky** PR Comment（`update_strategy`）。

> 本阶段 **不做** 完整 LLM / Web UI / SaaS 化（留给后续里程碑）。

## 架构（M2）

```
GitHub / smee.io ──► apps/api (FastAPI)
                        │ HMAC-SHA256 (X-Hub-Signature-256)
                        │ Redis SET NX 去重 X-GitHub-Delivery
                        │ arq.enqueue_job("process_pr")
                        ▼ 尽快 202
                     Redis (arq)
                        │
                        ▼
                  apps/worker (arq)
                        │ GET default_branch + contents/.pr-sentinel.yml
                        │ deep_merge(DEFAULT_CONFIG, repo_yml)
                        │ packages/github 拉 PR files（分页+截断）
                        │ RulesAnalyzer（secrets / large_files / weakened_tests）
                        │ ignore_paths 先过滤
                        └─► sticky issues/{n}/comments（update|recreate|skip_if_exists）
```

## 目录

```
apps/api/                 FastAPI：POST /webhooks/github
apps/worker/              arq WorkerSettings + process_pr
packages/common/          settings / arq 队列 / delivery 去重 / DEFAULT_CONFIG / 配置合并
packages/github/          GitHub 客户端 + App JWT + 规则引擎 + sticky comment
examples/.pr-sentinel.yml 示例仓库配置
.pr-sentinel.yml.example  同上（仓库根副本）
deploy/docker-compose.yml
tests/
```

## 配置（`.pr-sentinel.yml`）

- Worker **只读 default branch** 上的 `.pr-sentinel.yml`（PR 分支上的配置忽略）。
- 合并策略：`deep_merge(DEFAULT_CONFIG, repo_yml)`。
- 文件不存在 / 解析失败 → 仅用 `DEFAULT_CONFIG`，并在报告中注明。
- Fixture 模式：读 `tests/fixtures/pr-sentinel.yml`。

示例见 [`examples/.pr-sentinel.yml`](./examples/.pr-sentinel.yml) / [`.pr-sentinel.yml.example`](./.pr-sentinel.yml.example)。

关键字段：

| 字段 | 说明 |
| --- | --- |
| `update_strategy` | `update`（默认 PATCH）/ `recreate`（删旧再 POST）/ `skip_if_exists` |
| `ignore_paths` | glob，匹配文件不进入规则扫描 |
| `rules.secrets` | patch/文件名正则 |
| `rules.large_files` | 按 patch 长度 / additions 启发式 |
| `rules.weakened_tests` | 删除测试文件或 assert 净减少 |
| `analyzer.mode` | `rules`（默认）或 `fake` |
| `diff.max_*` | 分页与截断；截断时报告正文声明 **Limits 截断** |

## 认证

| 场景 | 方式 |
| --- | --- |
| **生产** | GitHub App：`GITHUB_APP_ID` + private key + webhook `installation.id` → JWT → `POST /app/installations/{id}/access_tokens` |
| **本地 / 兜底** | `GITHUB_TOKEN`（PAT / fine-grained） |
| **无凭据演示** | `USE_FIXTURES=true` 读 `tests/fixtures/`，不打真网 |

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
```

仅在完全没有 Secret 的纯 curl 调试时才设 `WEBHOOK_SKIP_VERIFY=true`。

## 快速开始

### 安装

```bash
cd pr-sentinel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Docker Compose

```bash
docker compose -f deploy/docker-compose.yml up --build
curl http://localhost:8000/health
```

服务：`api`（:8000）+ `worker`（arq）+ `redis` + `postgres`（空库占位）。

### 本地分进程

```bash
# 终端 1 — Redis
redis-server

# 终端 2 — API
export PYTHONPATH=.:packages:packages/github:apps/api
export USE_FIXTURES=true
uvicorn main:app --app-dir apps/api --reload --port 8000

# 终端 3 — arq Worker
export PYTHONPATH=.:packages:packages/github:apps/worker
export USE_FIXTURES=true
python apps/worker/main.py
# 或: arq apps.worker.main.WorkerSettings
```

## Sticky Comment 幂等

Marker（按 PR 稳定，**不**随 `head_sha` 变）：

```text
<!-- pr-sentinel:summary:{owner}/{repo}:{pr_number} -->
```

- `update`：已有 marker → `PATCH`；否则 `POST`。
- `recreate`：删旧再 `POST`。
- `skip_if_exists`：已有 marker 则跳过。

## Diff 拉取

`GET /repos/{owner}/{repo}/pulls/{n}/files`，分页 + 截断：

- `DIFF_MAX_PAGES` / config `diff.max_pages`（默认 5）
- `DIFF_PER_PAGE` / `diff.per_page`（默认 100）
- `DIFF_MAX_FILES` / `diff.max_files`（默认 300）

截断时报告中标注 **Limits 截断声明**。

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

## 许可

MIT — 见 [LICENSE](./LICENSE)。
