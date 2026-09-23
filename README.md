# PR Sentinel

GitHub PR 质量闸门 — **M1 可演示骨架**：Webhook HMAC 验签 → Delivery 去重 → **arq** 入队 → Worker 拉 diff → 假分析 → **Sticky** PR Comment。

> 本阶段 **不做** 完整 LLM / Web UI / 规则引擎 / SaaS 化（留给 M2+）。

## 架构（M1）

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
                        │ packages/github 拉 PR files（分页+截断）
                        │ FakeAnalyzer + 内置默认配置
                        └─► sticky issues/{n}/comments
```

## 目录

```
apps/api/                 FastAPI：POST /webhooks/github
apps/worker/              arq WorkerSettings + process_pr
packages/common/          settings / arq 队列 / delivery 去重 / 默认配置
packages/github/          GitHub 客户端 + 假分析 + sticky comment
deploy/docker-compose.yml
tests/
```

## 认证

| 场景 | 方式 |
| --- | --- |
| **生产（目标）** | GitHub App（`GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` + installation）。M1 为**占位**，JWT→installation token 交换在 M2 |
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

- `GET .../issues/{n}/comments` → 若已有 marker → `PATCH`；否则 `POST`。  
- `synchronize` 只更新同一条 sticky summary。

## Diff 拉取

`GET /repos/{owner}/{repo}/pulls/{n}/files`，分页 + 截断：

- `DIFF_MAX_PAGES`（默认 5）
- `DIFF_PER_PAGE`（默认 100）
- `DIFF_MAX_FILES`（默认 300）

截断时报告中标注。配置与内置 `DEFAULT_CONFIG`（等同未来 `.pr-sentinel.yml`）一致；**M1 不读仓库文件**。

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

## 许可

MIT — 见 [LICENSE](./LICENSE)。
