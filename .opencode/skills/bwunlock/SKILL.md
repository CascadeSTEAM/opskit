---
name: bwunlock
description: Refresh the vault session cache when it is stale or locked — run bin/bwunlock.sh (default opens a zenity password popup; --check never writes), or fall back to the manual one-liner. Use for: bwunlock, bw unlock, vault locked, vault session, bitwarden session, lockout, password popup, session cache
mode: skill
triggers: bwunlock,bw unlock,vault locked,vault session,bitwarden session,password popup,session cache,stale token
---

# bwunlock

`bw unlock --raw` needs the master password at a terminal, so a non-interactive
shell (agent harness, no TTY) cannot refresh `~/.cache/opskit/bw-session` left
stale by an auto-lock. This skill resolves that without ever holding or printing
the master password (opskit #378).

## Decision rules

- **Session resolution is NOT yours to re-derive.** All precedence (env var wins,
  mode check, single default path) lives in `bin/bw_session.py`. Run
  `bin/bwunlock.sh`, or call the resolver, never read `BW_SESSION` yourself.
- **`bin/bwunlock.sh --check`** resolves and probes the vault — prints where the
  session came from and whether the vault reports unlocked; exit 0 usable, 1
  not. Never prompts, never writes.
- **`bin/bwunlock.sh`** (no arg) refreshes: pops a zenity password dialog only
  when the session is unusable AND a display is present; otherwise degrades to
  the manual one-liner and exits 1. Never hangs on hidden `bw` input.
- **Password hygiene:** the master password crosses into `bw` via an env var +
  `--passwordenv` only — never on argv (`ps`-visible), never on disk, never in
  your output. The new token is written atomically with umask 077 and is never
  echoed.

## Workflow

1. Check state: `bin/bwunlock.sh --check`.
   - Exit 0 → report `vault session usable: unlocked (from <source>)`. Done.
   - Exit 1 → report the stale/locked/missing state + source.
2. Refresh (vault locked or session file empty/missing):
   `bin/bwunlock.sh` — a password popup appears for the operator to complete.
   - If the script degrades to the manual hint (no display/zenity), hand the
     printed `(umask 077; bw unlock --raw > <path>)` one-liner to the operator
     to run in a terminal; wait for confirmation.
   - If the session came from an exported `BW_SESSION` env var, the script says
     to re-export it — there is no file to write; do not try to refresh the
     cache file instead.
3. Verify: rerun `bin/bwunlock.sh --check`; it must exit 0.

## Caller pointers (kept in sync by mcp-run.sh / bw_session messages)

- `bin/mcp-run.sh` prints `/bwunlock` when the vault is LOCKED. Whatever MCP
  tool tripped it can be retried once the session is refreshed.
- `bin/bw_session.py --check`/`--token` errors mention `bin/bwunlock.sh`.

## Do NOT

- Do not run `bw unlock` yourself and read/capture the token into context.
- Do not `export BW_SESSION=<value>` into a session-notes file, issue, or PR.
- Do not relax the session file to group-readable to "fix" a permission error —
  use `chmod 600` or re-export.