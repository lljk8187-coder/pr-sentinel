# Live E2E 联调记录（模板）

> 复制本文件后填写。勿粘贴密钥 / PEM / PAT / webhook secret / ADMIN_TOKEN。  
> 参考：[docs/e2e-demo.md](../e2e-demo.md) · `scripts/preflight_live.py` · [records README](./README.md)

- **日期**：YYYY-MM-DD
- **操作者**：
- **仓库**：`owner/repo`
- **PR Sentinel 版本 / commit**：

---

## 1. 环境

- [ ] Compose / 本机进程已启动（api + worker + redis + postgres）
- [ ] `USE_FIXTURES=false`
- [ ] Auth：App（`GITHUB_APP_ID` + PEM 或 PATH） / 或 PAT（`GITHUB_TOKEN`）——**勿写密钥**
- [ ] `GITHUB_WEBHOOK_SECRET` 已配置且与 App Webhook Secret 一致（只写「已配置」）
- [ ] `WEBHOOK_SKIP_VERIFY=false`（推荐）
- [ ] `ADMIN_TOKEN` 已配置（只写「已配置」）

备注：

## 2. App / Install

- [ ] GitHub App 已创建
- [ ] Repository permissions含：**Checks Read & write**、Contents Read、Pull requests R/W、Issues R/W
- [ ] 已 Install 到测试仓；新权限已 Accept
- App ID：（数字即可）
- installation id：（来自真实 webhook / 安装页；**非** smoke 假 ID）

备注：

## 3. smee / Webhook

- [ ] smee channel → `http://127.0.0.1:8000/webhooks/github`（或公网 URL）
- [ ] App Webhook URL 指向 smee / 公网
- [ ] 试验投递或开 PR 后 API 日志可见 webhook（非 401）

smee / 公网 URL（可打码 channel 片段）：

## 4. Preflight 结果摘要

```bash
python scripts/preflight_live.py
```

- exit code：`0` / `1`
- FAIL 数：
- WARN 摘要（如 `/health` 未起）：
- PASS 项是否含 live `USE_FIXTURES` + App/PAT：

（粘贴脚本输出时确认无密钥全文；一般仅有 `set (chars=…)`。）

## 5. 触发与产物

- PR URL：
- delivery_id / job_id：
- 控制台：http://localhost:8000/console/jobs/<id> （或等价）

| 检查项 | 出现？ | 备注 |
| --- | --- | --- |
| Postgres / 控制台 job success（或可解释的 failed） | [ ] | |
| Check Run `pr-sentinel` | [ ] | URL： |
| Sticky summary comment | [ ] | |
| Inline review comment（若有 high+ findings） | [ ] | |
| Findings 含 source / rule_id（控制台详情） | [ ] | |

## 6. 截图说明（勿贴密钥）

| 说明 | 文件名或外链 | 已脱敏？ |
| --- | --- | --- |
| 控制台任务列表 / 详情 | | [ ] |
| PR 上 Check Run | | [ ] |
| Sticky / inline | | [ ] |

## 7. 失败排查（如有）

| 现象 | 已查 | 结论 |
| --- | --- | --- |
| 401 invalid signature | [ ] | |
| Check Run 403 | [ ] | 是否缺 Checks 权限 |
| Live missing credentials | [ ] | |
| 无评论 / 无 Check Run | [ ] | installation_id / fixtures / 权限 |
| 其他 | [ ] | |

## 8. 结论

- [ ] 联调目标达成
- [ ] 未达成（原因一句话）：

签字 / 备注：
