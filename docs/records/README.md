# 联调证据落盘（docs/records · M36）

本目录用于 **可选** 记录一次真实 GitHub App / live 端到端联调的证据摘要，方便复盘与验收对照。

## 已入库证据（脱敏）

| 记录 | 说明 |
| --- | --- |
| [2026-09-24-phase11-live-e2e.md](./2026-09-24-phase11-live-e2e.md) | **首份填好的真 App live 证明**（Phase11 / 1.6.0）：App `pr-sentinel-live-e2e` → smee → HMAC → Check Run + sticky + inline（rules secrets）；触发 **PR#1 已关闭、未合入 main**；远程 live-e2e 分支已删 |


## 如何复现（可选）

真 App live 联调**不强制**；需要再走一遍时：

1. 步骤与 FAQ：[docs/e2e-demo.md](../e2e-demo.md)（权限 / PEM / installation_id / HMAC / smee）。
2. 开 PR 前静态预检：`python scripts/preflight_live.py`（期望 exit 0）。
3. 对照已有证据：[2026-09-24-phase11-live-e2e.md](./2026-09-24-phase11-live-e2e.md)（Phase11）；新跑完可再填一份 TEMPLATE。
4. 收尾：触发用的测试 **PR 可以关闭**（不必合入 main）；远程临时分支可删。测试用 GitHub App **可保留**，也可在 GitHub 设置里**手动卸装**——**不要**用 API 自动卸 App。

## 何时填

| 场景 | 是否需要 |
| --- | --- |
| 默认 fixtures smoke（`USE_FIXTURES=true` + `scripts/smoke_fixtures_webhook.py`） | 一般不需要 |
| 即将或刚完成 **真 App + smee + 开 PR** 联调 | 建议：复制模板填一份 |
| CI / 日常开发 | 不需要 |

**默认不强制**每人再跑一遍真 App；仓库已有首份脱敏 live 证明（上表）。日常仍以 fixtures smoke 为主。

## 怎么用

1. 先按 [docs/e2e-demo.md](../e2e-demo.md) 完成真 App 配置，并用 `python scripts/preflight_live.py` 做静态预检（exit 0）。
2. 复制模板：

   ```bash
   cp docs/records/TEMPLATE-live-e2e.md docs/records/YYYY-MM-DD-live-e2e.md
   # 或私有命名：docs/records/local-YYYY-MM-DD-live-e2e.md（见下方 gitignore）
   ```

3. 按勾选清单填写；截图可放同目录或外链，**不要**贴密钥 / PEM / webhook secret 全文。

## 与 preflight / e2e-demo 的关系

```
docs/e2e-demo.md          步骤与 FAQ（怎么做）
scripts/preflight_live.py 开 PR 前静态自检（配置是否像 live）
docs/records/             做完后可选证据落盘（发生了什么）
```

预检通过 ≠ 联调成功；记录里应写清 Check Run / sticky / inline / 控制台 job 是否实际出现。

## 脱敏规则（必读）

**禁止**写入或提交：

- `GITHUB_APP_PRIVATE_KEY` / PEM 全文、PAT、`ADMIN_TOKEN`、`GITHUB_WEBHOOK_SECRET` 全文
- `.env` 内容、installation token、JWT
- 含密钥的截图（模糊或裁剪）

**可以**写：

- App ID（数字）、installation id（数字）、owner/repo、PR URL、job UUID、Check Run URL
- preflight 的 PASS/FAIL/WARN **摘要**（脚本本身不会回显密钥全文）
- 「截图：控制台 success 行」等说明文字；截图文件若含敏感信息勿入库

## Git 约定

- **可提交**：本 `README.md`、`TEMPLATE-live-e2e.md`
- **默认忽略**（见仓库根 `.gitignore`）：`*.pem`、`docs/records/**/secrets*`、`docs/records/local-*`、`docs/records/**/*-filled.md` 等真实填好的副本与附件
- 若确需把脱敏后的记录入库，使用不含密钥的文件名（例如 `2026-09-24-live-e2e.md`）并人工确认无敏感字段后再 `git add -f` 或调整 ignore——默认仍建议留在本地 `local-*` 命名下
