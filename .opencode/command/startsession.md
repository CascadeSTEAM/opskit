---
description: Bring the opskit repo and its subfolders up to date at session start
---

# startsession

Run the session-start update. Load the `startsession` skill
(`.opencode/skills/startsession/SKILL.md`) and execute its procedure exactly:

1. Usage tracking: `python3 bin/automation-ladder.py tick --skill startsession`
2. Sync the repo: `git fetch --all --prune && git pull` (on current branch)
3. Verify hooks: `git config core.hooksPath` must be `.githooks`; if not, run
   `bash bin/setup-hooks.sh`
4. Check subfolders that are their own repos: `git worktree list` and
   `bin/env-sync.sh <env> status` for each env under `environments/` except
   `example/`
5. Report one line per item — synced, or what is blocked and why

Do not edit, commit, or start infra work as part of this — it only brings the
tree up to date.
