---
name: gh
description: Drive a GitHub issue through the full opskit fix workflow — assign, worktree, linked branch, plan-to-issue, implement, test, PR that closes it, review. Use when the operator says "fix issue N", "/gh N", or "work issue N".
mode: skill
triggers: gh, fix issue, work issue, take issue, /gh, resolve issue
---

# gh

> Load when the operator wants a GitHub issue taken through the standard
> opskit fix workflow: `/gh <issue-number>`.

`bin/fix-issue.sh` does the deterministic plumbing; **you** do the judgment
steps (plan, fix, tests, review). Never skip a step or a test.

## Workflow (all eight steps, in order)

1. **Setup** — `bin/fix-issue.sh setup <n>`. This assigns the issue to the
   operator, creates the issue-linked branch, and adds a worktree beside the
   repo. Note the printed `worktree=` path and **switch into it** before any
   edits (all work happens in the worktree, never on `main`).
2. **Plan** — investigate root cause (reproduce it), decide the fix, and post
   the plan as a comment on the issue: `gh issue comment <n> --body "..."`.
   Keep it client-fact-free (see `docs/client-data-policy.md`).
3. **Implement, documenting as you go** — make the fix. Update device YAMLs /
   docs / skill registries in the same session per
   `.opencode/rules/document-as-you-go.md`. Report progress as milestones land.
4. **Test thoroughly** — `make test` (full suite), `shellcheck`/`bash -n` on
   touched scripts, and a functional check of the changed behaviour. A failure
   is fixed, not deferred (`.opencode/rules/definition-of-done.md`).
5. **PR** — `bin/fix-issue.sh pr <n> --title "<conventional title>" --body "<summary>"`.
   It prepends `Closes #<n>`, requests the `technology-support` reviewer, and
   assigns the operator. Verify CI goes green.
6. **Critical review + fix cycle** — adversarially review your own diff
   (edge cases, regressions, behaviour changes). Fix what you find, then
   **offer** to merge — do not merge unprompted.
7. **After merge** — `bin/fix-issue.sh cleanup <n>` removes the worktree and
   deletes the local branch.

## Rules

- Honour every repo hard rule: linked branch (never `main`), full test gate,
  PR closes the issue, reviewer ≠ author, definition-of-done.
- If setup fails (issue missing, branch exists), stop and report — don't guess.
- One issue per run. For a batch, run `/gh` once per issue.

## Related

- `bin/fix-issue.sh` — the mechanics (`setup` / `pr` / `cleanup`).
- `.opencode/rules/definition-of-done.md`, `.opencode/rules/document-as-you-go.md`.
