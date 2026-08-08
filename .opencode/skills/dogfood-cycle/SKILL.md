---
name: dogfood-cycle
description: Rapid-cycle dogfooding — run the real thing against real data, fail, fix, retry until MVP; escalate to a full dev cycle only on a true blocker
mode: skill
triggers: dogfood,dogfooding,try it,rapid cycle,mvp,iterate,smoke test,does it actually work
---

# dogfood-cycle

**Try it → fail → fix it → try again.** Tight loops against the real thing, until
either an **MVP** (Minimum Viable Product) goal is reached, or a genuine blocker
forces a bug report and a full dev cycle.

A working mode, not a phase. It is what you do *instead of* calling something
done because its tests pass.

## Why it earns a skill

One pass against a single live site found four defects a green test suite had
missed:

- a filename suffix silently becoming part of a URL route
- an empty route rewritten to an unreachable hash URL, so the homepage vanished
- a Link field whose target record nothing created, failing on any fresh target
- a stale route cache returning 403 to every visitor after records were replaced

Each appeared within minutes of *using* the thing. None were visible from
reading code, and none would have been caught by a unit test, because every one
lived in the gap **between** components rather than inside one. That gap is what
this cycle is for.

## The loop

1. **Pick a real target.** Real data, real service, real payloads, in a
   disposable environment. Synthetic fixtures do not surface these defects —
   that is the whole point.
2. **Use it the way a user would.** Not "does the function return" — browse the
   page, run the playbook, read the output.
3. **Diagnose before fixing.** Read the actual mechanism. A guess that happens to
   work leaves the real cause in place. One of the four above looked exactly like
   a permissions problem and was a cache problem; chasing the symptom would have
   fixed nothing.
4. **Fix, then immediately retry the same step.** Do not batch fixes — one
   change, one retry, or you cannot tell which fix worked.
5. **Reset to a genuinely fresh target before retrying.** Otherwise you verify
   the fix against state your previous attempt already repaired, and the bug
   comes back for the next person.
6. **Record every real defect where it will be seen again** — an issue, a test,
   a runbook note. Fixing without recording guarantees rediscovering.
7. **Loop until MVP.** Minimum viable, not complete.

## When to break the loop

Escalate to a bug report and a full dev cycle **only** for an actual blocker:
something that cannot be fixed from inside the loop — an upstream defect, a
missing capability, or a decision that is not yours to make. Capture it per the
never-lose-an-idea principle (`bin/idea.py add`, or an `issues/` file if it is
already concrete) and move on rather than grinding.

Everything else stays in the loop. "This needs a proper refactor first" is
usually the loop talking you out of finishing.

## Using it here

- **Disposable targets:** prefer a throwaway container, a scratch site, or a
  non-production environment. Never dogfood against a client's live system
  without saying so first.
- **Read-only first.** Probe and observe before writing anything.
- Anything touching a live host still goes through the normal access path —
  load `frappe-access` for Frappe work, and the relevant domain subagent
  otherwise. Rapid cycling changes the cadence, never the access rules.
- Repetition is a signal: a cycle you run three times is a candidate for
  `bin/automation-ladder.py`.
