# Golden 抽样用例（Phase10）

本目录存放规则 / LLM 的可复现抽样 case，供后续里程碑做回归与 score（M39+）。
M38 起提供目录、loader 与烟测；M39/M40 填入 rules/llm 样本；汇总分数见仓库根 `scripts/golden_score.py`（M41，默认不因分数失败）。

## 布局

```
tests/golden/
  loader.py          # load_case(path) → dict
  rules/             # kind=rules 的 JSON case
  llm/               # kind=llm 的 JSON case
  README.md
```

## JSON 约定

顶层字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 稳定短 id（文件名可与 id 不同） |
| `kind` | 是 | `"rules"` 或 `"llm"` |
| `files` | rules 必填 | PR 文件列表（与现有规则单测同形：`filename` / `patch` / …） |
| `response` | llm 必填 | 模拟的 LLM 解析输入（结构留给 M40） |
| `expect` | 是 | 见下 |

### `expect`

- **正例** `must_hit`：必须出现的命中列表
- **反例** `must_not`：不得出现的命中列表

每条命中期望：

| 键 | 必填 | 说明 |
|----|------|------|
| `rule_id` | 是 | 规则或 LLM finding 的 id |
| `path` | 是 | 文件路径（对应 finding 的 filename） |
| `line` | 否 | 行号；省略则只按 rule_id+path 匹配 |

示例（正例）：

```json
{
  "id": "example-secrets-akia",
  "kind": "rules",
  "files": [
    {
      "filename": "config.env",
      "status": "modified",
      "patch": "@@ -0,0 +1 @@\n+AWS_KEY=AKIAIOSFODNN7EXAMPLE\n"
    }
  ],
  "expect": {
    "must_hit": [{"rule_id": "secrets", "path": "config.env"}],
    "must_not": []
  }
}
```

## Loader

```python
from golden.loader import load_case, GoldenCaseError

case = load_case("tests/golden/rules/example_secrets_hit.json")
# case["id"], case["kind"], case["files"]|case["response"], case["expect"]
```

无效 JSON 或缺字段会抛 `GoldenCaseError`（消息含路径与原因）。

## 明确不做（本目录 / M38）

- 改规则实现、打真 OpenAI、升版本号
- score 汇总（M41）、塞满 5 规则样本（M39）
