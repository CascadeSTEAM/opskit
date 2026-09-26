---
name: vikunja-user
description: "Create a user account in a tenant's Vikunja instance via bin/vikunja-add-user.py. Vikunja has no admin REST API for this (registration is disabled and its /register endpoint is disabled right along with it, by upstream design) -- the only path is the vikunja user create CLI, run on the host over SSH + pct exec. Use for: vikunja user, add vikunja user, create vikunja account, vikunja invite"
mode: skill
triggers: vikunja user,add vikunja user,vikunja account,vikunja invite,vikunja set-admin
---

# vikunja-user

> Unlike `vikunja-ticket`, this is **not** an HTTP/MCP integration. Vikunja
> has no REST API for admin-initiated user creation — verified against
> upstream docs and the community forum: disabling registration
> (`enableregistration: false`, how BMS Vikunja is configured) disables
> `/register` too, on purpose, with no API alternative offered. The only way
> to create an account is the tenant's own `vikunja user create` CLI command,
> run on the host that runs the binary — Linux-server-ops territory
> (`AGENTS.md` routes this through `@linux`), reached over SSH + `pct exec`.

## Quick Reference

| Need | Command |
|---|---|
| Create a (non-admin) user, auto-generated password | `bin/vikunja-add-user.py <tenant> --username <name> --email <email>` |
| ...with a password you already chose | `... --password '<value>'` |
| Create and immediately promote to admin | `... --admin` |

Output is JSON: `{"tenant", "username", "email", "created", "verified", "password", ...}` on success, `{"error": "..."}` on failure — it never raises out to the caller.

## Steps

1. Confirm the tenant key — check `mcp/tenants-vikunja.local.json` (gitignored)
   for an `"exec"` block (`ssh_host`/`ctid`/`exec_user`/`binary`/`config_path`).
   No block, or a tenant missing one of those keys, is a config gap, not a
   guess to fill in — the tool refuses and names what's absent.
2. Omit `--password` to get a strong random one generated per call — prefer
   this over inventing a value. Either way, the password travels to the
   remote command over stdin, **never** as a `--password` argv value: argv is
   readable by any local user on that host via `ps`/`/proc/<pid>/cmdline`,
   the same exposure class `vikunja-ticket`'s curl fallback was fixed for.
3. `--admin` runs `vikunja user set-admin <user> --admin` only after the
   create call itself succeeds. Default every other user to non-admin —
   promoting is deliberate, not the default.
4. Report the returned `password` back to the operator **once**, as a
   one-time bootstrap value — relay it to the new user out-of-band and have
   them change it immediately. Never write it into a session note, an issue,
   a PR, or any other tracked file (`.opencode/rules/no-plaintext-creds.md`).
   This tool doesn't store it anywhere either; once printed, it's gone.
5. Check `verified` in the result — it's `true` only if the username showed
   up in a follow-up `vikunja user list` on that same host. `false` is worth
   a second look even though `created` was `true`; it doesn't undo the
   create, just flags a `user list` parsing mismatch worth a manual check.

## Failure handling

- Unknown tenant, missing/incomplete `exec` block: a readable `{"error": "..."}`
  before any SSH/network call — fix the tenant config, don't guess a host or
  CT id.
- `vikunja user create` itself failing (e.g. a duplicate username) surfaces
  the remote command's own stderr in `{"error": "..."}`, and nothing is
  created — safe to retry after fixing the cause.
- A `--admin` promotion failing *after* a successful create is a `warnings`
  entry on a success envelope, never a bare error — the account is real, so
  don't recreate it; just re-run `vikunja user set-admin` by hand (through
  `@linux`) once the cause is fixed.
- SSH/`pct exec` failures (unreachable host, `sudo` misconfigured, wrong
  `ctid`) show up as a non-JSON or empty stderr from the remote side — read
  it literally; this tool doesn't add its own retry logic, so a connect-level
  failure is safe to just re-run.

## Related

- `bin/vikunja-add-user.py` — the tool itself; see its own docstring for the
  authoritative interface and the tenant exec-config shape.
- `vikunja-ticket` skill / `mcp/vikunja-mcp-server.py` — the HTTP/MCP sibling
  integration for task creation; shares the same tenant file, a different
  key (`exec` vs. `base_url`), because the two operations reach the tenant
  over genuinely different transports.
- `.opencode/skills/vikunja-user/PLAN.md` — design rationale, including why
  this isn't (and can't be) an MCP tool.
- `ssh-access` skill / `@linux` subagent — the routing convention this skill
  rides on for the underlying SSH + `pct exec` access.
