---
name: vikunja-user
description: "Manage a user account's full lifecycle in a tenant's Vikunja instance via bin/vikunja-manage-user.py -- create, list, update, enable/disable, delete, reset-password, set-admin. Vikunja has no admin REST API for any of this (registration is disabled and its /register endpoint is disabled right along with it, by upstream design) -- the only path is the vikunja user CLI, run on the host over SSH + pct exec. Use for: vikunja user, add vikunja user, create vikunja account, vikunja invite, disable vikunja user, delete vikunja user, reset vikunja password, vikunja set-admin"
mode: skill
triggers: vikunja user,add vikunja user,vikunja account,vikunja invite,vikunja set-admin,disable vikunja user,delete vikunja user,vikunja reset password,vikunja list users
---

# vikunja-user

> Unlike `vikunja-ticket`, this is **not** an HTTP/MCP integration. Vikunja
> has no REST API for admin-initiated user management — verified against
> upstream docs and the community forum: disabling registration
> (`enableregistration: false`, how at least one tenant here is configured)
> disables `/register` too, on purpose, with no API alternative offered.
> The only way to create, update, disable, delete, or reset an account is
> the tenant's own `vikunja user <subcommand>` CLI, run on the host that
> runs the binary — Linux-server-ops territory (`AGENTS.md` routes this
> through `@linux`), reached over SSH + `pct exec`.

## Quick Reference

| Need | Command |
|---|---|
| Create a (non-admin) user, auto-generated password | `bin/vikunja-manage-user.py <tenant> create --username <name> --email <email>` |
| ...with a password you already chose | `... --password '<value>'` |
| Create and immediately promote to admin | `... --admin` (requires Vikunja Pro — see below) |
| List all users (raw CLI output, plus admin status if `db_name` is configured) | `bin/vikunja-manage-user.py <tenant> list` |
| Change username/email | `bin/vikunja-manage-user.py <tenant> update <user> --username <new>` / `--email <new>` |
| Disable / re-enable an account | `bin/vikunja-manage-user.py <tenant> disable <user>` / `enable <user>` |
| Request account deletion (safe default) | `bin/vikunja-manage-user.py <tenant> delete <user>` |
| Delete immediately (irreversible) | `... delete <user> --now` |
| Request a password-reset email (safe default) | `bin/vikunja-manage-user.py <tenant> reset-password <user>` |
| Set a password directly, auto-generated | `... reset-password <user> --direct` |
| Promote/demote instance admin | `bin/vikunja-manage-user.py <tenant> set-admin <user> --admin` / `--no-admin` |

`<user>` is a username **or** a numeric id everywhere except most
subcommands actually require the numeric id upstream — pass either; this
tool resolves a username to its id via `user list` first when needed (see
Steps). Output is JSON on every subcommand: a result dict on success,
`{"error": "..."}` on failure — it never raises out to the caller.

## Steps

1. Confirm the tenant key — check `mcp/tenants-vikunja.local.json` (gitignored)
   for an `"exec"` block (`ssh_host`/`ctid`/`exec_user`/`binary`/`config_path`).
   No block, or a tenant missing one of those keys, is a config gap, not a
   guess to fill in — the tool refuses and names what's absent.
2. **Numeric id vs. username**: upstream, `update`/`enable`/`disable`/`delete`/
   `reset-password` all take a numeric user id, not a username — `set-admin`
   is the one exception that accepts either. Passing a username to any of
   the id-only subcommands resolves it first via `vikunja user list`: zero
   or ambiguous matches are an error, never a guess, same convention every
   other resolver in this repo follows (`user list` has no documented
   output format, so this stays a best-effort token match).
3. Omit `--password` on `create`/`reset-password --direct` to get a strong
   random one generated per call — prefer this over inventing a value.
   Either way, the password travels to the remote command over stdin,
   **never** as a `--password` argv value: argv is readable by any local
   user on that host via `ps`/`/proc/<pid>/cmdline`, the same exposure
   class `vikunja-ticket`'s curl fallback was fixed for.
4. **`delete` and `reset-password` default to emailing the user**, exactly
   like upstream's own self-service flow — nothing happens until they act
   on that email. `--now` (delete) / `--direct` (reset-password) act
   immediately instead; `--now` is explicitly irreversible upstream
   ("USE WITH CAUTION" in Vikunja's own docs) — never pass it without the
   operator explicitly asking for an immediate, non-reversible delete.
5. **`set-admin` requires an active Vikunja Pro license** with the admin
   panel feature (upstream's own requirement, not a bug in this tool) — a
   self-hosted community-edition instance will fail this call outright.
   `create --admin` inherits the same constraint; its failure is a
   `warnings` entry on the create's success envelope, not a bare error,
   because the account already exists by then. `is_admin` is still a real
   column on the `users` table regardless of license — Pro only gates the
   *management* surface (admin panel, `/api/v1/admin/*`), not the
   underlying data — which is why `list` can still report it (next point)
   even on a Pro-less instance.
6. **`list`'s admin status comes from a direct, read-only Postgres query**,
   not the CLI or API — the only path that works without a Pro license.
   It only runs when the tenant's exec config sets `db_name`; without it,
   `list` behaves exactly as before (raw CLI output only). When configured
   but the query itself fails, that's a non-fatal `admin_status_error` on
   the result — the CLI-based listing still comes back.
7. Report any returned `password` back to the operator **once**, as a
   one-time bootstrap value — relay it to the new/affected user
   out-of-band and have them change it immediately. Never write it into a
   session note, an issue, a PR, or any other tracked file
   (`.opencode/rules/no-plaintext-creds.md`). This tool doesn't store it
   anywhere either; once printed, it's gone.
8. On `create`, check `verified` in the result — it's `true` only if the
   username showed up in a follow-up `vikunja user list` on that same
   host. `false` is worth a second look even though `created` was `true`;
   it doesn't undo the create, just flags a `user list` parsing mismatch
   worth a manual check.

## Failure handling

- Unknown tenant, missing/incomplete `exec` block: a readable `{"error": "..."}`
  before any SSH/network call — fix the tenant config, don't guess a host or
  CT id.
- Username resolution finding zero or multiple candidates in `user list` is
  a `{"error": "..."}` before any mutating call — pass the numeric id
  directly if you have it, or double-check the spelling.
- The remote `vikunja user <subcommand>` call itself failing (e.g. a
  duplicate username on `create`, a missing Pro license on `set-admin`)
  surfaces the remote command's own stderr in `{"error": "..."}` — read it
  literally, this tool doesn't add its own retry logic.
- A `--admin` promotion failing *after* a successful `create` is a
  `warnings` entry on a success envelope, never a bare error — the account
  is real, so don't recreate it; just re-run `set-admin` once the cause
  (usually: no Pro license) is addressed.
- SSH/`pct exec` failures (unreachable host, `sudo` misconfigured, wrong
  `ctid`) show up as a non-JSON or empty stderr from the remote side — read
  it literally; safe to just re-run since nothing here retries automatically.
- `list`'s admin-status query failing (wrong `db_name`, `psql` not on PATH,
  Postgres unreachable) is an `admin_status_error` field alongside a
  perfectly good `raw` listing — not a failure of `list` itself.

## Related

- `bin/vikunja-manage-user.py` — the tool itself; see its own docstring for
  the authoritative interface and the tenant exec-config shape.
- `vikunja-ticket` skill / `mcp/vikunja-mcp-server.py` — the HTTP/MCP
  sibling integration for task creation; shares the same tenant file, a
  different key (`exec` vs. `base_url`), because the two operations reach
  the tenant over genuinely different transports.
- `/vikunja` slash command — routes to this skill or `vikunja-ticket`
  depending on whether the request is about an account or a task.
- `.opencode/skills/vikunja-user/PLAN.md` — design rationale, including why
  this isn't (and can't be) an MCP tool.
- `ssh-access` skill / `@linux` subagent — the routing convention this skill
  rides on for the underlying SSH + `pct exec` access.
