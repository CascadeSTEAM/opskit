---
name: docwright-lifecycle
description: DocWright document lifecycle management - proposals, plans, completed/canceled transitions
distributable: true
---

# DocWright Lifecycle Skill

## Document Lifecycle

```
proposals/  →  proposals/approved/  →  plans/  ─→  plans/completed/ (completed → docs/)
(proposal)      (approved)              (exec)     ↘  plans/completed/ (canceled, no docs)
```

## Key Rules

1. **Proposals:** `approved: false` initially. Only humans set `approved: true`.
2. **Move to approved/:** Requires `approved: true` AND non-empty `assigned_to`.
3. **Plan execution:** Requires `status: approved|in-progress` AND non-empty `assigned_to`.
4. **Completion:** Set `status: completed`, move to `plans/completed/`, generate docs in `docs/`.
5. **Cancellation:** Set `status: canceled`, add `canceled_date` + `cancellation_reason`, move to `plans/completed/`, NO docs.
6. **Agents NEVER set `approved: true`** on proposals.

## Plan Modes

- `off` — Mentorship: human executes, LLM advises
- `guided` — LLM drafts/stages, human approves (LLM cannot set `approved: true`)
- `full` — LLM executes autonomously, pauses for user input via `waiting_for_user`

## Required Frontmatter

| Document | Required Fields |
|----------|----------------|
| Proposal | `title`, `author`, `created`, `tags`, `approved`, `created_by`, `assigned_to` |
| Plan | `title`, `status`, `author`, `created`, `tags`, `proposal_source`, `priority`, `automated` |
| Completed | `title`, `status: completed`, `author`, `created`, `completed_date`, `proposal_source` |
| Canceled | `title`, `status: canceled`, `canceled_date`, `cancellation_reason` |

## Actions

- `proposal.approved=true + assigned_to non-empty` → move to approved/, create plan
- `plan fully implemented` → status=completed, move to completed/, generate docs
- `plan obsolete` → status=canceled, canceled_date, cancellation_reason, move to completed/ (no docs)
