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
   - Pure public-repo dev session → `docs/session-notes/`
   - Session touched live infrastructure (client or org, incl. mixed
     sessions) → `environments/<env>/session-notes/` ONLY, pushed via
     `bin/env-sync.sh <env> push`; the public SESSION-LOG entry stays
     terse and infrastructure-state-free
   Contents either way:
   - Commands run
   - Errors encountered
   - Undo instructions
4. Append strategic entry to `SESSION-LOG.md`:
   - Key decisions
   - Architectural choices
   - Open threads
5. Stage and commit all remaining changes
6. Push all branches to origin
7. Report final status: commits pushed, branches status, any uncommitted work

## Do NOT

- Never skip the session note — it is the operational audit trail
- Never leave uncommitted infrastructure changes at session end
