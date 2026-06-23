---
name: zentao-bug-fixer
description: Use when the user wants Codex to work with a self-hosted ZenTao instance for bug repair or QA test case upload, including choosing a product, choosing an assignee, listing unresolved ZenTao bugs, repairing local code, verifying changes, adding ZenTao bug notes, and batch uploading AI-generated test cases to ZenTao.
---

# ZenTao Bug Fixer

## Overview

Use this skill to turn ZenTao bug reports into local code fixes. The current working directory is the business project to modify; this skill only supplies the ZenTao workflow, API helpers, and safety rules.

## Configuration

Read configuration from environment variables first:

```bash
export ZENTAO_BASE_URL="https://your-zentao.example.com/zentao"
export ZENTAO_ACCOUNT="your-account"
export ZENTAO_PASSWORD="your-password"
# Optional:
export ZENTAO_API_PREFIX="/api.php/v1"
export ZENTAO_TESTCASE_API_PREFIX="/api.php/v2"
export ZENTAO_TOKEN="existing-token"
export ZENTAO_RESOLVED_BUILD="主干"
export ZENTAO_RESOLVE_BUG_AFTER_COMMENT="1"
```

Never write credentials, tokens, private ZenTao domains, or product IDs into this skill. For project-local defaults, prefer an untracked `.zentao.json` in the business repository:

```json
{
  "productId": 8,
  "productName": "Example Product"
}
```

If the current shell does not already export the ZenTao variables, the helper scripts auto-load them from `.env` in the skill install directory.

## Workflow

1. Confirm the current working directory is the business codebase the user wants modified.
2. Check for uncommitted local changes before editing. Work with existing user changes; do not revert them.
3. Use `scripts/zentao_bug_flow.py` or `scripts/zentao_client.py` to get product and bug context.
4. If no product is known, list products and ask the user to choose one.
5. List unresolved bugs whose Bug type is a code issue, group them by `assignedTo`, and ask the user which assignee's repairable bugs to batch repair.
6. Process every unresolved code-issue bug assigned to the selected user, one bug at a time.
7. For each bug, fetch full bug details and summarize the title, reproduction steps, expected result, priority, severity, environment, and keywords.
8. Search the business project with `rg` and repair the code using the repository's existing patterns.
9. Run the most relevant verification command available in the business project.
10. When the repair is complete, add a ZenTao note containing the root cause and solution. By default do not change the bug status; if `ZENTAO_RESOLVE_BUG_AFTER_COMMENT` or `--resolve-bug-after-comment` is enabled, mark the bug as resolved after the note succeeds using `resolvedBuild=主干` unless `ZENTAO_RESOLVED_BUILD` or `--resolved-build` overrides it.
11. Report changed files, verification result, root cause, solution, and the ZenTao note result.

## Test Case Upload Workflow

Use this path when the user has AI-generated test cases and wants to upload them to ZenTao:

1. Ask for or create a JSON batch file containing either an array of cases or an object with `defaults` and `cases`.
2. Require every final case to have `productID` and `title`; accept `product`, `productId`, or `product_id` as aliases for `productID`.
3. Prefer shared values such as `productID`, `module`, `type`, `pri`, `project`, and `execution` under `defaults`.
4. Normalize step objects like `{"step": "操作", "expect": "结果"}` into ZenTao `steps`, `expects`, and `stepType` arrays.
5. Run `testcase-upload` with the JSON file. Use `--continue-on-error` only when the user explicitly wants partial batch upload behavior.
6. Report how many cases were created, failed, and any returned ZenTao IDs.

The helper first tries `POST /api.php/v2/testcases`. If a self-hosted instance returns an empty response body for that v2 route, it automatically falls back to the logged-in web JSON form route `/testcase-create-{productID}-all-{module}.json`.

Example JSON:

```json
{
  "defaults": {
    "productID": 8,
    "module": 0,
    "type": "feature",
    "pri": 3
  },
  "cases": [
    {
      "title": "登录成功后进入首页",
      "precondition": "账号已注册",
      "steps": [
        {"step": "输入正确账号密码", "expect": "登录按钮可点击"},
        {"step": "点击登录", "expect": "进入首页"}
      ]
    }
  ]
}
```

## API Helpers

List products:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py products
```

Batch upload test cases:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py testcase-upload ./zentao-testcases.json
```

Continue after individual test case failures:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py testcase-upload ./zentao-testcases.json --continue-on-error
```

List unresolved code-issue bugs for a product:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py bugs 8
```

Include non-code bug types only for inspection:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py bugs 8 --include-non-code
```

Read a bug:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py bug 6025
```

Update a bug type:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py bug-update 6025 --type others
```

Supported type values are `codeerror`, `config`, `install`, `security`, `performance`, `standard`, `automation`, `designdefect`, and `others`. Common Chinese labels such as `代码问题` are normalized to the matching ZenTao value.

Run the interactive selector:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_bug_flow.py
```

Add a cause and solution note after the local repair is complete:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py comment 6025 \
  --cause "消息附件数组只读取了第一项。" \
  --solution "遍历全部附件并逐条生成消息内容。"
```

Resolve a bug without adding a note:

```bash
python3 /path/to/zentao-bug-fixer/scripts/zentao_client.py resolve 6025
```

The helper targets ZenTao API paths commonly exposed as:

- `POST /api.php/v1/tokens`
- `GET /api.php/v1/products`
- `GET /api.php/v1/products/:id/bugs`
- `GET /api.php/v1/bugs/:id`
- `PUT /api.php/v1/bugs/:id`
- `POST /api.php/v1/bugs/:id/resolve`
- `POST /api.php/v2/testcases`
- `POST /action-comment-bug-:id.json`

If a self-hosted ZenTao instance customizes these paths, inspect its own `dev-api-restapi.html` and adjust `scripts/zentao_client.py` conservatively.

## ZenTao Note Update

When a bug has been repaired and local verification has passed, add a ZenTao note without asking for another confirmation. Write the note in this exact Chinese format:

```text
问题原因：
具体原因内容

解决方案：
具体解决方案内容

---------
通过 <zentao-bug-fixer> Skill 自动完成问题分析与修复。
```

- `问题原因`: 单独占一行，下一行开始写中文原因内容。
- `解决方案`: 单独占一行，下一行开始写中文解决方案内容。
- 分隔线 `---------` 必须单独占一行，位于解决方案和尾注之间。
- 尾注 `通过 <zentao-bug-fixer> Skill 自动完成问题分析与修复。` 必须作为整个备注的最后一段追加，不能省略。

By default only send the `comment` field through the action comment endpoint. If resolve-after-comment is enabled, send the comment first, then call the resolve endpoint with `resolution=fixed` and `resolvedBuild`; `resolvedBuild` defaults to `主干` and can be overridden with `ZENTAO_RESOLVED_BUILD` or `--resolved-build`. The standalone `resolve` subcommand uses the same resolve endpoint and default build, without writing a comment. Do not send `status`, `resolvedBuild`, `resolvedBy`, `closedBy`, or any other lifecycle field through the comment endpoint. QA or the user handles other status transitions separately when resolve-after-comment is not enabled.

Do not delete bugs, close bugs, resolve bugs, edit unrelated fields, or update bugs that were not repaired in the current run.

## Batch Mode

When the user chooses an assignee, process that assignee's unresolved code-issue bugs one at a time:

1. Fetch detail.
2. Repair locally.
3. Verify.
4. Add the cause and solution note to ZenTao. Keep the bug open unless the resolve-after-comment switch is enabled.
5. Continue to the next bug only after the current bug is handled or skipped.

Do not make one large mixed change for multiple unrelated bugs unless the bugs clearly share the same root cause.

## Open-Source Hygiene

Keep this skill portable:

- Use only standard-library Python unless a dependency becomes unavoidable.
- Keep all private data in environment variables or ignored local config.
- Do not commit tokens, cookies, screenshots with private bug data, or organization-specific URLs.
- Keep scripts deterministic and usable from any Codex business project.
