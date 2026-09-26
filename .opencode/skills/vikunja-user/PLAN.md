# Plan: Vikunja user-management tool (opskit #402, extended #404)

Goal: let the agent create a real Vikunja account (username + email,
non-admin by default) and report a one-time password, without inventing a
new credential-handling anti-pattern along the way.

## Why this isn't a `vikunja-ticket`-shaped MCP tool

`vikunja-ticket` works because Vikunja's REST API covers task CRUD. User
creation is different: checked against upstream docs
(`vikunja.io/docs/cli/`) and the community forum thread "How to create user
accounts?" (maintainer reply, verbatim substance): with registration
disabled — which is how at least one tenant's instance in this repo is
actually configured (`enableregistration: false`, its env dataset notes
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

- **`bin/vikunja-manage-user.py`** (renamed from `vikunja-add-user.py` in
  #404, once its scope outgrew "add") — one function per action
  (`create_user`, `list_users`, `update_user`, `set_status`, `delete_user`,
  `reset_password`, `set_admin`), each taking `run=subprocess.run` as an
  injected seam so tests never touch a real socket/subprocess (mirrors how
  `mcp/vikunja-mcp-server.py`'s tests monkeypatch `get_client`, not
  `requests` itself).
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
    `--password` argv value. Every interpolated value (`username`, `email`,
    `config_path`, `binary`, `exec_user`) is `shlex.quote()`-escaped before
    joining — ssh hands its remote-command string to the target's own shell,
    so an unescaped username containing `;`/backticks/`$()` would execute
    arbitrary commands on the Vikunja host as its own service user (caught
    in review, opskit #402).
  - After a successful create, runs `vikunja user list` on the same host and
    checks the username appears in its output at a word boundary (not a bare
    substring test — a plain `in` check false-positives when the new
    username is a substring of an unrelated existing one, e.g. creating
    `ali` while `alice` already exists; also caught in review) — best-effort
    verification, not a hard gate (the CLI's list output isn't documented as
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
call against a real instance is the check (see Verification); if it
fails, the fallback is `--password` with the generated value still
constructed at *this* privilege boundary (never chosen by an agent as a
guessable string) — an argv-exposure risk to accept explicitly, not to
silently reintroduce.

## Verification

1. `python3 -m pytest tests/test_vikunja_manage_user.py` — offline, argv-shape
   and stdin-vs-argv assertions, error paths, `--admin` sequencing.
2. First live call: `bin/vikunja-manage-user.py <tenant> create --username '<test>' --email
   '<test>@example.org'`, then confirm in the Vikunja admin UI that the
   account exists and that the stdin-fed password actually worked (the CLI's
   TTY assumption above, resolved live rather than guessed) — this is
   exactly the kind of fact `vikunja-ticket`'s own plan flagged as "taken
   from memory rather than a live call" until it had one.
3. Delete or disable the test account afterward: `bin/vikunja-manage-user.py
   <tenant> delete <test> --now` (immediate) — or `disable <test>` to keep it
   around inert instead.

## Deliberately out of scope (v1, #402)

No bulk/batch creation, no team assignment, no password reset flow (that's
`vikunja user reset-password`, a separate concern), no email-invite (Vikunja
has no CLI-triggered invite email; the operator relays the one-time password
themselves). Add more only once a real need shows up, same discipline
`vikunja-ticket`'s plan already set.

## Extension: full account lifecycle (opskit #404)

Added once the operator asked for "fully managing users," not just create.
Same architecture, same tool, five more actions plus the rename above.

Upstream facts fetched **verbatim** from `vikunja.io/docs/cli/` (not a
paraphrase, to avoid compounding an already-thin evidence base with a
second layer of guessing):

- `user update [user id]`, `user change-status [user id]`, `user delete
  [id]`, `user reset-password [user id]` all take a **numeric id**.
  `user set-admin [username-or-id]` is the one documented exception that
  accepts either — so `set_admin()` passes its `identifier` straight
  through, unlike every other new action.
- `user delete` without `--now` **only emails the user a confirmation
  link** — the same flow as self-service deletion, and nothing is deleted
  until they act on it. `--now` deletes immediately: upstream's own docs
  say "USE WITH CAUTION." `reset_password()` mirrors this same
  safe-by-default shape: no `--direct` means an email, `--direct` sets the
  password immediately (over stdin, generated if omitted, never argv —
  same fix class as `create`).
- `user set-admin` **"Requires an active Vikunja Pro license with the
  admin panel feature."** A self-hosted community-edition tenant (which is
  what this repo's own deployed instance is) will fail this call outright.
  That's not a bug to catch here — it surfaces as an ordinary `RuntimeError`
  with the CLI's own stderr, same as any other remote failure. Documented
  prominently in SKILL.md so an operator doesn't mistake a license error
  for a broken tool.
- `user list` still has no documented output format or `--output json`
  flag, so id resolution has the exact same evidentiary status as
  `create`'s post-create verification: best-effort, never a silent guess.

**`_resolve_user_id()`** is the one new piece of real logic: a numeric
identifier is used as-is (no network call); a username runs `user list`
and looks for lines whose tokens include it exactly, taking the first
digit-token on each matching line as an id candidate. Zero candidates or
disagreeing candidates across multiple lines is a `LookupError` naming
what happened, never a guess — same "zero or ambiguous is an error"
convention as project/label/user matching everywhere else in this repo.
Tokenizing splits on runs of non-word/`@`/`.`/`-` characters rather than
plain whitespace, so a comma- or pipe-separated table parses the same as
a whitespace-aligned one — `user list`'s actual format is still unverified
against a live instance, so this stays deliberately permissive rather than
betting the whole feature on one guessed table shape.

**Deliberately out of scope for #404 too**: bulk/batch operations (each
call still manages exactly one account), and anything that would require
an actual Vikunja Pro license to test against (only documented, not built
around blindly).
