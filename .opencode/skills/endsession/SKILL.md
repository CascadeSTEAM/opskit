---
name: endsession
description: Automated session shutdown — saves session note, updates SESSION-LOG.md, commits all remaining changes, pushes all branches, reports status
mode: skill
triggers: endsession, end session, shutdown, wrap up, session end
---

# Session Shutdown Skill

Triggered by: "endsession", "end session", "shutdown"

## Procedure

0. **Definition-of-done check (hard gate — see
   `.opencode/rules/definition-of-done.md`).** Before wrapping up, confirm each:
   - Ideas that drove the work are `accepted`/`consolidated` with a GH# in
     `docs/ideas.md` — not left `new` (`python3 bin/idea.py list --status new`).
   - Non-trivial work has an issue + linked branch, not an unrelated branch.
   - Docs/device-YAMLs/skill registries match what changed this session.
   - `make test` is green.
   - Machine checks pass: `python3 bin/definition-of-done-guard.py --cached`
     (also runs in pre-commit/CI — new tool→test, new skill→registered, no stubs).
   Anything unfinished that cannot be completed now gets a follow-up issue
   before the session closes.
1. Verify all planned work is committed
2. Review `git status` for any remaining changes
3. Write the session note — ROUTE BY SESSION TYPE (hard rule,
   docs/client-data-policy.md "Facts leak too"):
   - Pure public-repo dev session → `docs/session-notes/` (a real commit,
     so it follows step 5 below — worktree + PR, same as any other
     opskit-repo file)
   - Session touched live infrastructure (client or org, incl. mixed
     sessions) → `environments/<env>/session-notes/` ONLY, committed and
     pushed directly via `bin/env-sync.sh <env> push` (exempt from the
     worktree rule — see AGENTS.md hard rule #2); the `SESSION-LOG.md`
     entry stays terse and infrastructure-state-free
   Contents either way:
   - Commands run
   - Errors encountered
   - Undo instructions
4. Append a strategic entry to `SESSION-LOG.md` — key decisions,
   architectural choices, open threads. This file is gitignored, local to
   this clone (opskit #217) — edit it directly, no commit/PR needed for
   this specific file, regardless of which branch or worktree you're in.
5. Stage and commit everything else that changed. Per AGENTS.md hard rule
   #2, any opskit-repo file (`docs/session-notes/` entries, code, other
   docs) needs its own worktree + linked branch + PR — never a direct
   commit on the shared primary checkout. `environments/<env>/` files are
   the exception: commit and push those directly in place.
6. Push all branches to origin (and open/merge PRs for anything from
   step 5 that needed one).
7. Report final status: commits pushed, branches/PRs status, any
   uncommitted work.

## Do NOT

- Never skip the session note — it is the operational audit trail
- Never leave uncommitted infrastructure changes at session end
