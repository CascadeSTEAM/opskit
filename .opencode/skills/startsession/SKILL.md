---
name: startsession
description: Bring the opskit repo and its subfolders up to date at session start — git fetch/pull on the current branch, verify .githooks hooksPath, and check worktrees and gitignored environment layers via env-sync.sh. Use when starting a session, or when told to update/sync this project folder and any subfolders.
mode: skill
triggers: startsession,start session,session start,update project folder,update this project,sync repo,project update
---

# Startsession

<!-- Scaffolded by bin/automation-ladder.py. Replace the placeholder
     steps but KEEP step 0: it is how the automation ladder measures
     whether this skill deserves a codified script/tool. -->

## Steps

0. **Usage tracking (always, before anything else):**

   ```bash
   python3 bin/automation-ladder.py tick --skill startsession
   ```

   If the output has `"offer_upgrade": true`, tell the operator this
   skill has crossed the usage threshold and offer to codify it. Target
   selection (IaC rule): if this skill changes the state of ANY system —
   remote host or the local workstation — the codified form is an
   **Ansible playbook/role** in `ansible/`; a plain script only for
   repo/dev workflow. Offer an MCP tool under `mcp/` if a
   playbook/script already backs it. If they decline permanently, run
   `python3 bin/automation-ladder.py mute --skill startsession`
   so they are never asked again.

1. **Sync before anything (hard rule, AGENTS.md "Git & GitHub Workflow" #1):**
   On the current branch, before any other work:

   ```bash
   git fetch --all --prune && git pull
   ```

   If the pull fails (conflict, diverged), STOP and report — do not merge or
   rebase on your own.
2. **Verify hooks are wired (hard rule "Hooks auto-setup"):**

   ```bash
   git config core.hooksPath   # must print .githooks
   ```

   If it does not, run `bash bin/setup-hooks.sh` and confirm it prints `.githooks`.
3. **Update subfolders that are their own repos:**
   - Worktrees: `git worktree list` — pull each one on its own branch.
   - Environment layers (gitignored, private): `bin/env-sync.sh <env> status`
     for each dir under `environments/` except `example/`; run `clone`/`pull`
     as it reports. A bare `git pull` never touches these.
4. **Report back:** one line each for repo sync, hooks path, and each
   subfolder/Env layer — state synced, or what is blocked and why.

## Failure handling

- `git pull` conflict or divergent branches → STOP, report the affected
  branch and files, ask how to proceed. Never force-push or merge blindly.
- `env-sync.sh` reports unpushed/uncloned work → report it; do not push
  without the operator's go-ahead (single-branch layers refuse non-default
  pulls/pushes).

## Do NOT

- Do not start infra work from this skill alone — infra changes additionally
  require `switch-env.sh` + a helpdesk ticket (see AGENTS.md "Session start
  sequence"). This skill only brings the repo tree up to date.
- Do not edit or commit anything while doing the update itself.
