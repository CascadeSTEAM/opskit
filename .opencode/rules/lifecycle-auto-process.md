---
rule: lifecycle-auto-process
description: Defines what frontmatter changes trigger automated lifecycle transitions via lifecycle-processor.py
---

# Lifecycle Auto-Processing Rules

## Trigger Map

When `lifecycle-processor.py --check` or `--watch` detects these frontmatter states,
it processes the corresponding transition:

| Detected State | Automated Action | Constraint |
|----------------|------------------|------------|
| `proposal.approved: true` + `assigned_to` non-empty | Move proposal to `proposals/approved/`, create plan from template | NEVER set `approved: true` yourself |
| `proposal.approved: true` + `assigned_to` empty | Block. Log: "Human must set assigned_to first" | |
| `plan.status: completed` | Move plan to `plans/completed/`. Git commit. Print doc-generation reminder | Verify all steps were done |

## Safety Constraints

1. **Never set `approved: true`** on any proposal or plan.
2. **Never create a plan** from a proposal with empty `assigned_to`.
3. **Always verify** frontmatter by reading the file before acting.
