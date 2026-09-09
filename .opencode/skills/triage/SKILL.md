---
name: triage
description: "Repo-wide critical review: triage GitHub backlog, review code at a SHA, file measurable findings, apply one priority rubric"
triggers: "/triage,triage repo,repo triage,triage issues,triage code,triage the backlog,critical review,reconcile issues,prioritize issues,priority sweep"
---

# triage skill

Load this skill when the user asks to review the repo, triage issues, or reconcile the GitHub backlog.

## Modes

- `full` — full pass (default): survey issues, partition code, code review, consolidate, score, report
- `code` — review specific paths only
- `issues` — survey open issues only
- `ideas` — triage docs/ideas.md ledger only
- `board` — board plan dry-run or apply
- `status` — re-print latest report
- `apply` — re-present report and ask again, then apply

## Procedure

See `docs/triage.md` for the full runbook. Key steps:

1. `bin/triage.py survey` — survey open GitHub issues
2. `bin/triage.py partition` — assign every file to an area
3. Code review per area (read-only, ≤10 findings each)
4. `bin/triage.py rubric` — score every finding
5. Consolidate and deduplicate findings
6. Generate report at gate — wait for typed "go"
7. Apply changes after approval

## Measurability Rule

Every finding must have `## Observed`, `## Measure` (with `baseline:` and `target:`), and `## Verify` (a command or test). "Refactor", "consistency", "cleanup" without a measured effect fail the gate.

## Priority Rubric

Single source: `priority_label()` in `bin/triage.py`.
- Impact 5 → `priority:urgent` (if observable now) or `priority:high`
- Impact 4 → `priority:high`
- Impact 3 → `priority:medium`
- Impact 1–2 → `priority:low`

Speed is recorded for the report only, never moves a label.

## Do NOT

- Close issues without evidence (merged PR targeting the issue)
- Apply changes without the operator's typed "go"
- Report findings without `baseline:` and `target:`
- Use bare `triage` as a trigger (claimed by `idea-triage`)

## Related

- `bin/triage.py` — tool implementation
- `bin/fix-issue.sh` — issue creation/bumping/labeling
- `docs/triage.md` — full runbook
- `AGENTS.md:143` — skill registration line
