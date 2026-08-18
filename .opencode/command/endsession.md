---
description: Automated session shutdown — save session note, update SESSION-LOG.md, commit, push, report
---

# endsession

Run the session-end shutdown. Load the `endsession` skill
(`.opencode/skills/endsession/SKILL.md`) and execute its procedure exactly:

1. Definition-of-done check (hard gate): ideas accepted with GH# in
   `docs/ideas.md`, non-trivial work has an issue + linked branch, docs and
   registries match, `make test` green, machine checks pass
   (`python3 bin/definition-of-done-guard.py --cached`)
2. Verify all planned work is committed; review `git status` for leftovers
3. Write the session note — ROUTE BY SESSION TYPE (hard rule): public-repo dev
   → `docs/session-notes/` (worktree + PR); touched live infra →
   `environments/<env>/session-notes/` only, pushed via
   `bin/env-sync.sh <env> push`
4. Append a strategic entry to `SESSION-LOG.md` (gitignored — edit directly)
5. Stage and commit everything else that changed; opskit-repo files need a
   worktree + linked branch + PR, `environments/<env>/` commits directly
6. Push all branches to origin; open/merge PRs for anything that needed one
7. Report final status: commits pushed, branches/PRs status, uncommitted work

Do not skip the session note, and never leave uncommitted infrastructure
changes at session end.