---
name: lifecycle
description: Document lifecycle stages, plan modes, and key rules for proposals → plans → completed
mode: skill
triggers: lifecycle,proposal,plan,transition,completed,canceled,approved
---

# lifecycle

> Load this skill when creating, moving, or querying proposals, plans, or completed documents.

0. Track usage: `python3 bin/automation-ladder.py tick --skill lifecycle` — if the output has `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill lifecycle`.

## Stages

```
issues/  →  proposals/  →  proposals/approved/  →  plans/  →  plans/completed/  →  docs/
```

- **issues/** — raw intake, no approval gate, `status: open|promoted|closed`
- **proposals/** — `approved: false`; only humans set `approved: true`
- **plans/** — requires `status: approved|in-progress` + non-empty `assigned_to`
- **plans/completed/** — `status: completed` (with docs) or `status: canceled` (no docs)

## Plan Modes (`automated` field)

| Value | Meaning |
|-------|---------|
| `off` | Mentorship — human executes, LLM advises |
| `guided` | LLM drafts/stages, human approves each step |
| `full` | LLM executes autonomously, pauses only on `waiting_for_user` |

## Key Rules

- **Only humans** set `approved: true` — never agents
- Canceled plans get `canceled_date` + `cancellation_reason`; no doc is generated
- Query current state: `python3 bin/lifecycle-processor.py --status`
- Preview transitions: `python3 bin/lifecycle-processor.py --dry-run`

## Do NOT

- Do NOT grep frontmatter manually — use `lifecycle-processor.py --status`
- Do NOT create a plan without an approved proposal source
- Do NOT set `approved: true` — surface the proposal to the human operator instead
