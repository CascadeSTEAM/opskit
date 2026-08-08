---
name: cleanup
description: Prune the branch and worktree mess a backlog run leaves behind — report first, remove on one confirmation
mode: skill
triggers: cleanup,clean up,prune,tidy,stale branches,housekeeping
---

# cleanup

> Load this skill at the end of a `/plow`, or periodically on its own. A plow
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
- **A remote branch with no PR at all.** "Never had a PR" is not "finished", so
  that call is the operator's. These are listed separately for a decision.
- Anything that is not a branch or worktree metadata. Session notes, the idea
  ledger and the environment layers are out of scope — a cleanup that edits
  those is a different and much riskier thing.

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

- `plow` skill — invokes this as its final phase
- `docs/client-data-policy.md` — why branch names count as published
