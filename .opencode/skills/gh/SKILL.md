---
name: gh
description: Drive a GitHub issue through the full opskit fix workflow — assign, worktree, linked branch, plan-to-issue, implement, test, PR that closes it, review — or list issues. Use when the operator says "/gh N", "fix issue N", "work issue N", "/gh mine", or "/gh unassigned".
mode: skill
triggers: gh, fix issue, work issue, take issue, /gh, resolve issue
---

# gh

> Load when the operator wants a GitHub issue taken through the standard
> opskit fix workflow: `/gh <issue-number>`.

`bin/fix-issue.sh` does the deterministic plumbing; **you** do the judgment
steps (plan, fix, tests, review). Never skip a step or a test.

## Dispatch on the argument

- **`/gh mine`** → `bin/fix-issue.sh list mine` — open issues assigned to the
  operator. Just run it and show the output; no branch/worktree.
- **`/gh unassigned`** → `bin/fix-issue.sh list unassigned` — open issues with
  no assignee. Same: list only.
- **`/gh new`** → run the guided issue-creation cycle (see "Creating an issue").
- **`/gh <number>`** → run the full fix workflow below.

If the operator says `/gh` with no argument, offer both lists (`mine` first).

## Creating an issue (`/gh new`)

1. **Gather** — ask the operator to describe it in their words. Ask at most
   2-3 targeted follow-ups, and only if type / affected area / (for bugs)
   repro-vs-expected are unclear. Don't interrogate.
2. **Dedup — propose, operator disposes.** Search open AND closed issues
   (`bin/fix-issue.sh search <terms>`) plus `docs/ideas.md` and
   `proposals/plans/`. On a strong match, show it and ask: bump the existing
   one (`bin/fix-issue.sh bump <n> --priority … --note …`, adding the new info)
   vs create a genuinely-distinct new issue. Never auto-merge.
3. **Ledger off-ramp** — if it reads as a raw/vague idea rather than ready
   work, offer `bin/idea.py add …` (docs/ideas.md) instead of a full issue
   (the repo's anti-ticket-flood convention).
4. **Classify** — pick the native Issue **Type** (`Task`/`Bug`/`Feature`) and
   labels from the real set (`bug`/`enhancement`/`documentation`/…). Feature
   request → Type `Feature`. Milestone only if one exists and clearly applies.
5. **Draft, client-safe** — a proper title + structured body (Problem /
   Proposal / Definition of done). **Scrub client-identifying facts** — issues
   are public and the publication guard does NOT cover issue text.
6. **Confirm, then create** — show the full draft (title, body, Type, labels)
   and create only on explicit approval:
   `bin/fix-issue.sh new --type <T> --title "…" --body "…" [--label …]`.
   Report the returned number + title + URL.

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
