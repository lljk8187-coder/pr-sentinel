# PR Sentinel

GitHub PR 质量闸门 — **M3**：Webhook HMAC 验签 → Delivery 去重 → **arq** 入队 → Worker 读 **default branch** `.pr-sentinel.yml` → 拉 diff → **规则引擎 +（可选）OpenAI 兼容 LLM** → **Sticky** PR Comment（可重入 upsert）。

> 本阶段 **不做** 完整 Web UI / SaaS 化（留给 M4+）。

## 架构（M3）

```
GitHub / smee.io ──► apps/api (FastAPI)
                        │ HMAC-SHA256 (X-Hub-Signature-256)
                        │ Redis SET NX 去重 X-GitHub-Delivery
                        │ arq.enqueue_job("process_pr")
                        ▼ 尽快 202
                     Redis (arq)
                        │ max_tries=3 / job_timeout / Retry 退避
                        ▼
                  apps/worker (arq)
                        │ GET default_branch + contents/.pr-sentinel.yml
                        │ deep_merge(DEFAULT_CONFIG, repo_yml)
                        │ packages/github 拉 PR files（分页+截断）
                        │ Rules / Rules+LLM（无密钥 → llm_skipped）
                        │ privacy.redact_secrets 后再送 LLM
                        └─► sticky issues/{n}/comments（update|recreate|skip_if_exists）
```

## 目录

```
apps/api/                 FastAPI：POST /webhooks/github
apps/worker/              arq WorkerSettings + process_pr（重试）
packages/common/          settings / arq 队列 / delivery 去重 / DEFAULT_CONFIG
packages/github/          GitHub 客户端 + App JWT + 规则引擎 + llm.py + sticky
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
| `privacy.redact_secrets` | 送入 LLM 前对文本做密钥 redact（`***REDACTED***`） |
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
# 可选：填入 OPENAI_API_KEY 启用 LLM；不填则自动降级
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

重复跑 `process_pr` 只会 sticky update，不刷屏。

## Diff 拉取

`GET /repos/{owner}/{repo}/pulls/{n}/files`，分页 + 截断：

- `DIFF_MAX_PAGES` / config `diff.max_pages`（默认 5）
- `DIFF_PER_PAGE` / `diff.per_page`（默认 100）
- `DIFF_MAX_FILES` / `diff.max_files`（默认 300）

截断时报告中标注 **Limits 截断声明**。

## Worker 重试（M3）

`WorkerSettings`：`max_tries=3`、`job_timeout=300`、瞬态错误 `Retry(defer=…)` 退避。业务 skip（如 `summary_comment=false`）正常返回，不耗尽重试。

## 测试

```bash
pip install -r requirements.txt
pytest -q
```

## 许可

MIT — 见 [LICENSE](./LICENSE)。
