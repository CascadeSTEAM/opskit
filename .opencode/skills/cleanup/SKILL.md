---
name: cleanup
description: Prune the branch and worktree mess a backlog run leaves behind — report first, remove on one confirmation
mode: skill
triggers: /cleanup,cleanup,clean up,prune,tidy,stale branches,housekeeping
---

# cleanup

> Load this skill at the end of a `/grind`, or periodically on its own. A grind
> run creates a branch per issue and a worktree per review agent; none of the
> leftovers break anything, which is exactly why they pile up.

0. Track usage: `python3 bin/automation-ladder.py tick --skill cleanup` — if the
   output has `"offer_upgrade": true`, offer codification per Development
   Principles (repo script: this is dev-workflow); permanent "no" →
   `python3 bin/automation-ladder.py mute --skill cleanup`.

## Procedure

1. **Survey.** `bin/repo-cleanup.py` — reports only, deletes nothing.
2. **Show the operator the list**, including anything it declined to touch.
3. **Get one go-ahead for the batch**, then `bin/repo-cleanup.py --apply`.
4. **Report** what was removed, with SHAs.

That is the whole cycle. The tool holds the safety rules; this skill holds the
"report, confirm, then act" shape.

## What it removes

- Local branches fully merged into the default branch
- Remote branches whose PR is merged or closed
- Orphaned worktree metadata

## What it never removes, and why

- **A branch checked out in any worktree.** Several agent sessions share this
  clone; deleting a branch out from under one turns a tidy-up into an outage.
- **An unmerged branch** — it uses `git branch -d`, never `-D`.
- **The default branch.**
- **Any branch carrying commits the base branch lacks**, whatever its PR says.
  A *closed* PR means rejected or abandoned, not merged, so it gets the same
  scrutiny as a branch with no PR at all. These are listed separately, with
  their unmerged commit count, for a decision.
  (A no-PR branch that is provably an *ancestor* of the base holds nothing, so
  it is offered like any other dead branch — usually an abandoned
  `gh issue develop` stub, which is also why issue branches come back with a
  `-1` suffix.)
- Anything that is not a branch or worktree metadata. Session notes, the idea
  ledger and the environment layers are out of scope — a cleanup that edits
  those is a different and much riskier thing.

**One limitation, stated rather than hidden:** "in use" means *this clone*. If a
teammate on another machine has a branch checked out, deleting its remote still
removes their upstream. That is judged acceptable because the branch is only
offered when its PR is already merged or closed, so the content is in the
default branch and nothing is lost — but it is a real edge, not an oversight.

## Why remote branches matter

A branch name is published the moment it is pushed: it appears in the remote
branch list, CI logs and notifications, and survives in forks and clones after
deletion (#118). A branch list that is mostly dead is a standing, if small,
exposure, and it buries the live ones.

## Recovery

Every removal prints the SHA it was at. Restore with
`git branch <name> <sha>`, or `git push origin <sha>:refs/heads/<name>` for a
remote one.

## Related

- `grind` skill — invokes this as its final phase
- `docs/client-data-policy.md` — why branch names count as published
