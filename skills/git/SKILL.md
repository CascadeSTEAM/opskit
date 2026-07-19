---
name: git
description: Git commit format, atomic commit rules, and enforcement hooks for this repository
mode: skill
triggers: git,commit,push,branch,merge
---

# git

> Load this skill before making or reviewing any git commit in this repo.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill git` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 scripts/automation-ladder.py mute --skill git`.

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
- Post-commit hook auto-pushes to origin

## Do NOT

- Do NOT combine multiple unrelated changes in one commit
- Do NOT use past tense ("added X") — use imperative ("add X")
