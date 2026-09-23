# PR Sentinel

GitHub PR 质量闸门 — **M1 可演示骨架**：Webhook 验签 → Redis 入队 → Worker 拉 diff → 假分析 → 幂等 PR Comment。

> 本阶段 **不做** 完整 LLM / Web UI / 规则引擎 / SaaS 化（留给 M2+）。

## 架构（M1）

```
GitHub webhook ──► apps/api (FastAPI)
                      │ HMAC 验签
                      │ LPUSH job
                      ▼
                   Redis list
                      │ BRPOP
                      ▼
                apps/worker
                      │ packages/github 拉 PR files
                      │ FakeAnalyzer 生成固定报告
                      └─► 幂等 issues/{n}/comments
```

## 目录

```
apps/api/              FastAPI：POST /webhooks/github
apps/worker/           队列消费者
packages/common/       settings + Redis 队列
packages/github/       GitHub 客户端 + 假分析 + 幂等 comment
deploy/docker-compose.yml
tests/                 pytest + fixtures
```

## 快速开始

### 依赖

- Python 3.11+
- Redis（本地或 compose）
- （可选）Docker / Docker Compose

### 安装

```bash
cd pr-sentinel
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 开发可设 WEBHOOK_SKIP_VERIFY=true 与 USE_FIXTURES=true
```

### Docker Compose（推荐演示）

```bash
docker compose -f deploy/docker-compose.yml up --build
curl http://localhost:8000/health
```

服务：`api`（:8000）+ `worker` + `redis` + `postgres`（空库占位，API 暂不连）。

### 本地分进程

```bash
# 终端 1 — Redis（若无本机）
redis-server

# 终端 2 — API
export PYTHONPATH=.:packages:packages/github:apps/api
export WEBHOOK_SKIP_VERIFY=true USE_FIXTURES=true
uvicorn main:app --app-dir apps/api --reload --port 8000

# 终端 3 — Worker
export PYTHONPATH=.:packages:packages/github:apps/worker
export USE_FIXTURES=true
python apps/worker/main.py
```

### 模拟 Webhook

```bash
# 跳过验签时：
curl -X POST http://localhost:8000/webhooks/github \
  -H 'Content-Type: application/json' \
  -H 'X-GitHub-Event: pull_request' \
  -d '{
    "action":"opened",
    "pull_request":{"number":7,"head":{"sha":"deadbeefcafebabe000011112222333344445555"},"html_url":"https://github.com/acme/demo/pull/7"},
    "repository":{"full_name":"acme/demo","name":"demo","owner":{"login":"acme"}},
    "installation":{"id":1}
  }'
```

验签开启时，用 `GITHUB_WEBHOOK_SECRET` 对 body 做 HMAC-SHA256，放入 `X-Hub-Signature-256: sha256=<hex>`。

## 配置（`.env`）

| 变量 | 说明 |
| --- | --- |
| `GITHUB_WEBHOOK_SECRET` | Webhook HMAC 密钥 |
| `WEBHOOK_SKIP_VERIFY` / `ALLOW_INSECURE_WEBHOOKS` | 开发跳过验签 |
| `REDIS_URL` | 默认 `redis://localhost:6379/0` |
| `GITHUB_TOKEN` | 优先于 App 凭据 |
| `GITHUB_APP_ID` + `GITHUB_APP_PRIVATE_KEY` | App 占位（未配真 App 时走 fixture） |
| `USE_FIXTURES` | `true` 时读 `tests/fixtures/`，不打真网 |

## 幂等 Comment

Marker：`<!-- pr-sentinel:{head_sha} -->`

- 先 `GET .../issues/{n}/comments`
- 若已有同 SHA marker → `PATCH` 更新
- 否则 → `POST` 新建

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

覆盖：验签通过 / 失败、入队、幂等 update。

## 许可

MIT — 见 [LICENSE](./LICENSE)。
