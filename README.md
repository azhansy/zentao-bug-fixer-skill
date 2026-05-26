# zentao-bug-fixer

Codex skill for fixing bugs from a self-hosted ZenTao instance inside the current business codebase.

## Install

Clone or copy this repository into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R /path/to/zentao-bug-fixer ~/.codex/skills/zentao-bug-fixer
```

Restart Codex or open a new Codex session so the skill can be discovered.

## Configure

Set ZenTao connection information in your shell environment:

```bash
export ZENTAO_BASE_URL="https://your-zentao.example.com/zentao"
export ZENTAO_ACCOUNT="your-account"
export ZENTAO_PASSWORD="your-password"
```

Optional settings:

```bash
export ZENTAO_API_PREFIX="/api.php/v1"
export ZENTAO_TOKEN="existing-token"
```

Do not commit credentials, tokens, private domains, or project-specific product IDs.

## Use In A Business Project

Open Codex from the business codebase you want to modify, then ask:

```text
使用 zentao-bug-fixer 修复禅道 bug
```

Codex should then:

1. List ZenTao products and ask you to choose one.
2. List unresolved bugs for that product grouped by assignee.
3. Ask which assignee's unresolved bugs to batch repair.
4. Read each selected bug's details.
5. Modify the current business codebase.
6. Run relevant verification.
7. Add a ZenTao note with the root cause and solution. The bug status is not changed.

## Optional Project Binding

In a business project, you may create an untracked `.zentao.json` for local defaults:

```json
{
  "productId": 8,
  "productName": "Example Product"
}
```

Keep `.zentao.json` out of version control if it contains private project information.

## Helper Commands

List products:

```bash
python3 ~/.codex/skills/zentao-bug-fixer/scripts/zentao_client.py products
```

List unresolved bugs for product `8`:

```bash
python3 ~/.codex/skills/zentao-bug-fixer/scripts/zentao_client.py bugs 8
```

Read bug `6025`:

```bash
python3 ~/.codex/skills/zentao-bug-fixer/scripts/zentao_client.py bug 6025
```

Run the interactive selector:

```bash
python3 ~/.codex/skills/zentao-bug-fixer/scripts/zentao_bug_flow.py
```

Add a cause and solution note to a repaired bug:

```bash
python3 ~/.codex/skills/zentao-bug-fixer/scripts/zentao_client.py comment 6025 \
  --cause "Root cause summary" \
  --solution "Fix summary"
```

## Test

```bash
python3 -m unittest discover -s tests
```
