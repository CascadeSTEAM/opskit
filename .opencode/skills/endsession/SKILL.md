---
name: endsession
description: Automated session shutdown — saves session note, updates SESSION-LOG.md, commits all remaining changes, pushes all branches, reports status
mode: skill
triggers: endsession, end session, shutdown, wrap up, session end
---

# Session Shutdown Skill

Triggered by: "endsession", "end session", "shutdown"

## Procedure

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
