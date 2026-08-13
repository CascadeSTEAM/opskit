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

1. **Verify the primary checkout is on the default branch (hard rule,
   AGENTS.md "Git & GitHub Workflow" #2 — worktree required).** This
   directory may be shared by concurrent sessions; it should never be
   anywhere but `main` outside of a session actively mid-worktree-setup.

   ```bash
   git branch --show-current
   ```

   If it isn't the repo's default branch (`main`), STOP and report —
   don't switch it yourself. Being off-`main` here is itself a sign of the
   exact drift the worktree hard rule exists to prevent (another session
   may have left work in progress there), and silently switching could
   destroy it. Ask the operator how to proceed.
2. **Sync (hard rule, AGENTS.md "Git & GitHub Workflow" #1):** only once
   step 1 confirms `main`:

   ```bash
   git fetch --all --prune && git pull
   ```

   If the pull fails (conflict, diverged), STOP and report — do not merge or
   rebase on your own.
3. **Verify hooks are wired (hard rule "Hooks auto-setup"):**

   ```bash
   git config core.hooksPath   # must print .githooks
   ```

   If it does not, run `bash bin/setup-hooks.sh` and confirm it prints `.githooks`.
4. **Update subfolders that are their own repos:**
   - Worktrees: `git worktree list` — pull each one on its own branch.
   - Environment layers (gitignored, private): `bin/env-sync.sh <env> status`
     for each dir under `environments/` except `example/`; run `clone`/`pull`
     as it reports. A bare `git pull` never touches these.
5. **Pin this session's ticket if others may be working in this same
   checkout.** `.current-ticket` is shared, unscoped file state — any
   concurrent session that runs `switch-env.sh`/`open-ticket.sh` here
   silently clobbers it out from under every other session (hit live
   during opskit #209's handoff-skill rehearsal: a peer session switched
   environments mid-session and a later commit would have been tagged
   against the wrong ticket entirely). If more than one session might
   touch this checkout at once, export `OPSKIT_TICKET=<this session's
   ticket>` now — `bin/active_ticket.py` honors it over `.current-ticket`
   (opskit #158) — and re-supply it inline on every command that needs it,
   since exported shell state does not persist between separate tool
   calls in this harness. Skip this step for a genuinely solo session.
6. **Report back:** one line each for the branch check, repo sync, hooks
   path, each subfolder/Env layer, and whether a ticket pin was set —
   state synced, or what is blocked and why.

## Failure handling

- Primary checkout not on `main` → STOP, report the branch and its state
  (`git status`, `git log -1`), ask how to proceed. Never switch or discard
  it yourself.
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
