---
name: git
description: Git commit format, atomic commit rules, and enforcement hooks
mode: skill
triggers: git,commit,push,branch,merge
---

# git

> Load this skill before making or reviewing any git commit.

0. Track usage: `python3 bin/automation-ladder.py tick --skill git` — if the output has `"offer_upgrade": true`, offer codification per Development Principles (Ansible playbook if work changes system state, repo script if dev-workflow); permanent "no" → `python3 bin/automation-ladder.py mute --skill git`.

## Commit Message Format (MANDATORY)

```
<type>: <description>
```

| Type | Use for |
|------|---------|
| `feat` | New feature or proposal |
| `fix` | Bug fix or correction |
| `docs` | Documentation changes |
| `refactor` | Code/structure refactoring |
| `chore` | Maintenance, config, housekeeping |

## Key Rules

- **Atomic commits** — one logical change per commit; never batch unrelated changes
- **Commit immediately** after each logical change — don't accumulate
- Body is optional: explain WHY (not what — the diff shows what)

## Enforcement

- Pre-commit hook validates message format
- Pre-commit hook rejects secrets

## Do NOT

- Do NOT combine multiple unrelated changes in one commit
- Do NOT use past tense ("added X") — use imperative ("add X")
