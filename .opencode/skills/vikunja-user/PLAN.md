# Plan: Vikunja user-creation tool (opskit #402)

Goal: let the agent create a real Vikunja account (username + email,
non-admin by default) and report a one-time password, without inventing a
new credential-handling anti-pattern along the way.

## Why this isn't a `vikunja-ticket`-shaped MCP tool

`vikunja-ticket` works because Vikunja's REST API covers task CRUD. User
creation is different: checked against upstream docs
(`vikunja.io/docs/cli/`) and the community forum thread "How to create user
accounts?" (maintainer reply, verbatim substance): with registration
disabled — which is how BMS Vikunja is actually configured
(`environments/bms/datasets/devices/vikunja.md`: `enableregistration: false`,
"Invite users via the admin UI") — `/register` is disabled too, by design,
with no API alternative. "I wouldn't consider registration disabled if only
the buttons in the UI were hidden but the api endpoint still available" is
the maintainer's own framing. The only supported path is the CLI:
`vikunja user create -u <username> -e <email> [-p <password>]`, run on the
host that runs the binary.

Per `AGENTS.md`'s Development Principle #2, this is application-record state
(a real account inside a hosted app), which ordinarily means "the tool IS an
MCP tool" — but the principle's own text carves out the alternative that
applies here: "...or a codified CLI where no agent surface is needed." An
MCP server can't reach a CLI on a remote LXC any more directly than a skill
can; either way the operation is fundamentally a Linux-server-ops action
(`pct exec` into the tenant's container), which `AGENTS.md` already routes
through `@linux`, not through a new HTTP client.

## Architecture

- **`bin/vikunja-add-user.py`** (new) — one function, `create_user(tenant,
  username, email, password, make_admin, run=subprocess.run)`, plus a thin
  `main()`. `run` is an injected seam so tests never touch a real
  socket/subprocess (mirrors how `mcp/vikunja-mcp-server.py`'s tests
  monkeypatch `get_client`, not `requests` itself).
  - Reads the tenant's `exec` block from the **same** gitignored
    `mcp/tenants-vikunja.local.json` `vikunja-ticket` already uses — one
    tenant file, two transports (`base_url` for HTTP, `exec` for CLI), not a
    second config file that can drift from the first.
  - Resolves `ssh_host`/`ctid`/`exec_user`/`binary`/`config_path` by exact
    key presence; any tenant or key missing is an error naming exactly
    what's absent, never a guessed default — same convention as every other
    resolver in this repo (project/user/label matching in the sibling MCP
    server).
  - Builds `["ssh", "-o", "BatchMode=yes", <ssh_host>, "pct exec <ctid> --
    sudo -u <exec_user> <binary> user create --config <config_path> -u
    <username> -e <email>"]` and feeds the password over **stdin**, not a
    `--password` argv value.
  - After a successful create, runs `vikunja user list` on the same host and
    checks the username appears in its output — best-effort verification,
    not a hard gate (the CLI's list output isn't documented as
    machine-parseable JSON, so this is a substring check, not a strict
    schema match).
  - `--admin` runs `vikunja user set-admin <username> --admin` only after a
    successful create; its own failure is a `warnings` entry on a success
    envelope, never a bare `{"error": ...}` — the account already exists by
    then, so reporting only an error risks someone re-running create and
    hitting a duplicate-username failure for no reason.
- **`.opencode/skills/vikunja-user/SKILL.md`** — documents the CLI for any
  runtime, same shape as every other skill in this repo.
- **No MCP server, no new persistent process.** Every other detail
  (`@linux` routing, SSH alias discipline, `pct exec`) is already this
  repo's standing convention for reaching an LXC's own CLI; this tool is
  just the codified, tested version of that manual procedure.

## Password handling (the one real design decision here)

Passed over **stdin**, never `--password` on argv, even though the CLI
supports `--password` directly — matching the fix already applied to
`vikunja-ticket`'s curl fallback (its own PLAN.md, point 6: "Token passed on
argv... visible to any local user via `ps`/`/proc/<pid>/cmdline`"). The two
cases differ in stakes (a long-lived bearer token vs. a one-time bootstrap
password the new user is expected to rotate immediately) but the mechanism
of exposure is identical, so the same fix applies rather than re-litigating
whether this instance is "low-stakes enough" to skip it.

**Open / unverified**: whether the real `vikunja` binary's password prompt
reads cleanly from a non-TTY stdin pipe when `--password` is omitted is
taken from the CLI's documented behavior ("You will be asked to enter it if
not provided"), not confirmed against a live instance — some Go CLI prompt
libraries require a real terminal fd and fail on a plain pipe. First live
call against the real BMS instance is the check (see Verification); if it
fails, the fallback is `--password` with the generated value still
constructed at *this* privilege boundary (never chosen by an agent as a
guessable string) — an argv-exposure risk to accept explicitly, not to
silently reintroduce.

## Verification

1. `python3 -m pytest tests/test_vikunja_add_user.py` — offline, argv-shape
   and stdin-vs-argv assertions, error paths, `--admin` sequencing.
2. First live call: `bin/vikunja-add-user.py bms --username '<test>' --email
   '<test>@example.org'`, then confirm in the Vikunja admin UI that the
   account exists and that the stdin-fed password actually worked (the CLI's
   TTY assumption above, resolved live rather than guessed) — this is
   exactly the kind of fact `vikunja-ticket`'s own plan flagged as "taken
   from memory rather than a live call" until it had one.
3. Delete or disable the test account afterward — this tool has no
   `--delete`; use `vikunja user delete <id>` by hand through `@linux` if the
   test account shouldn't remain.

## Deliberately out of scope for v1

No bulk/batch creation, no team assignment, no password reset flow (that's
`vikunja user reset-password`, a separate concern), no email-invite (Vikunja
has no CLI-triggered invite email; the operator relays the one-time password
themselves). Add more only once a real need shows up, same discipline
`vikunja-ticket`'s plan already set.
