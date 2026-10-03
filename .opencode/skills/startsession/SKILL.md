---
name: startsession
description: Bring the opskit repo and its subfolders up to date at session start — git fetch/pull on the current branch, verify .githooks hooksPath, and check worktrees and gitignored environment layers via env-sync.sh. Use when starting a session, or when told to update/sync this project folder and its subfolders.
mode: skill
triggers: startsession,start session,session start,update project folder,update this project,sync repo,project update
---

# Startsession

**Primary tool:** `bin/startsession.sh` — a single-command codification of
the full session-start procedure (usage tracking, sync, hooks, worktrees,
env layers, context surfacing, vault check). Use this instead of running
the steps manually.

```bash
bash bin/startsession.sh                          # full run
bash bin/startsession.sh --no-fetch               # skip fetch (local state current)
bash bin/startsession.sh --no-env-pull            # status only for env layers
```

## Steps (for manual debugging or when the script fails)

0. **Usage tracking:** `python3 bin/automation-ladder.py tick --skill startsession`.
    If `"offer_upgrade": true` was just consumed (you are reading the
    codification it triggered), this is expected. If asked to `mute` instead,
    run `python3 bin/automation-ladder.py mute --skill startsession`.

1. **Branch check** — `git branch --show-current` must print the repo's
    default branch (`main`). If off-`main`, STOP and report; never switch
    it yourself (worktree hard rule).
2. **Sync** — `git fetch --all --prune && git pull`. If it fails, STOP and
    report; never force-merge.
3. **Hooks** — `git config core.hooksPath` must resolve to `.githooks`.
    If not, `bash bin/setup-hooks.sh`.
4. **Worktrees** — `git worktree list`, `git -C <path> pull --ff-only`
    for each (skip primary checkout and `worktree/` subdirectory).
5. **Env layers** — `bin/env-sync.sh <env> status` for each directory
    under `environments/` except `example/`. Report dirty/clean.
6. **Context surfacing:**
    - Read `RESUME.md` first line if present.
    - Check `.local/session-reminders.md` if present.
    - `bin/hd-ticket-triage.py --summary` (one-line, ignore errors).
    - Mail-auth freshness if `mail-domains.yml` exists.
7. **Vault check** — `bin/bwunlock.sh --check`. Exit 1 → offer to run
    the default form; never run it yourself.
8. **Report** — one line per item: branch, sync, hooks, each worktree,
    each env layer, context items, vault.

## Failure handling

- Primary checkout not on `main` → STOP, report the branch and its state
  (`git status`, `git log -1`), ask how to proceed.
- `git pull` conflict or divergent branches → STOP, report the affected
  branch and files, ask how to proceed.
- `env-sync.sh` reports unpushed/uncloned work → report it; do not push
  without the operator's go-ahead.
- Vault session stale → OFFER `bin/bwunlock.sh`; never auto-run it.

## Do NOT

- Start infra work from this skill alone — infra changes additionally
  require `switch-env.sh` + a helpdesk ticket (see AGENTS.md "Session
  start sequence"). This skill only brings the repo tree up to date.
- Edit or commit anything while doing the update itself.

## Failure handling

- Primary checkout not on `main` → STOP, report the branch and its state
  (`git status`, `git log -1`), ask how to proceed. Never switch or discard
  it yourself.
- `git pull` conflict or divergent branches → STOP, report the affected
  branch and files, ask how to proceed. Never force-push or merge blindly.
- `env-sync.sh` reports unpushed/uncloned work → report it; do not push
  without the operator's go-ahead (single-branch layers refuse non-default
  pulls/pushes).
- Vault session stale → OFFER `bin/bwunlock.sh`; never auto-run the writing
  form. A locked vault at session start is routine, not a blocker for the
  sync steps above.

## Do NOT

- Do not start infra work from this skill alone — infra changes additionally
  require `switch-env.sh` + a helpdesk ticket (see AGENTS.md "Session start
  sequence"). This skill only brings the repo tree up to date.
- Do not edit or commit anything while doing the update itself.
