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

## Extension: is_admin via direct DB read (opskit #406)

Added after the first live call against a real instance (#402/#404's own
"first live call" verification step, finally exercised): the operator
asked `list` to also show whether each user is an instance admin.

**Verified live, not guessed, before writing any code**: `vikunja user
list`'s real output is a box-drawn table (`ID │ USERNAME │ EMAIL │ STATUS │
ISSUER │ SUBJECT │ CREATED │ UPDATED`) — confirming `_resolve_user_id`'s
tokenizer handles it correctly (the timestamp columns' colon-separated
digit fragments could have collided with the true ID column; they don't,
because the ID column is always the first digit-token left to right, and
that's what the resolver takes). No admin column, no flags at all, matching
the CLI docs. Separately, `\d users` on the live Postgres instance showed
`is_admin boolean not null default false` as a real column, and `SELECT
id, username, is_admin, status FROM users` showed all ten real accounts —
including the original `admin` user — currently `is_admin = false`, with
the CLI itself logging `"No license key configured. Pro features have been
disabled."` on every invocation. So: the license gate is real and confirmed,
but it gates the *management* surface (admin panel, `/api/v1/admin/*`), not
the underlying column, which is exactly what makes a direct DB read the
right tool here rather than a dead end.

An AI-summarized web page had also claimed this same shape ("the flag
still exists in community mode") before the live check — treated as
unverified secondary evidence until confirmed directly against the real
schema and data, not taken on its own.

**Design**: `_remote()` was split into a generic `_remote_as(exec_cfg,
executable, *parts)` (still `pct exec <ctid> -- sudo -u <exec_user>
<executable> <parts>`, shell-quoted the same way) plus `_remote(exec_cfg,
*parts)` as the vikunja-binary-specific case every existing subcommand
already used — no behavior change for any of them. `build_admin_query_argv`
uses `_remote_as(exec_cfg, "psql", ...)` to run `SELECT username, is_admin
FROM users ORDER BY id` with `-t -A -F <tab>` (unaligned, tuples-only,
tab-separated) so parsing never depends on `user list`'s box-drawing
format — a completely different, trivially-parseable channel for this one
query.

A new **optional** per-tenant exec-config key, `db_name`: optional because
this is enrichment on `list`, not a requirement for `list` to keep doing
what it already did. Tenants without it get exactly the old behavior — no
new required config, no test changes needed for #402/#404's existing
suite. When set, `list_users()` runs the query and merges an `admins`
dict (`username -> bool`) into its result; when the query itself fails
(wrong `db_name`, `psql` missing, Postgres unreachable), that's a
non-fatal `admin_status_error` field, not a failure of `list` — the raw
CLI listing that already worked must keep working even if this newer,
less-exercised path breaks.

No new credential: still SSH host-key trust + passwordless sudo to the
`exec_user`, same as everything else — just a different program (`psql`
instead of the vikunja binary) invoked through the identical channel.
Confirmed live that local peer auth via the OS user needs no password.

**Deliberately out of scope**: any write path through this channel (this
is a `SELECT`, on purpose, nothing else), and surfacing `is_admin` anywhere
other than `list` (e.g. `create`'s result) until a real need shows up.

## Correction: instance admin ≠ team admin (opskit #408)

#406 shipped, got a live `list` call run against it, and the operator
immediately caught a real mistake: a known account was reported as
non-admin when they clearly were one, in the sense the operator meant.

**What #406 actually measured**: `users.is_admin`, the instance-wide
superadmin flag — accurately `false` for every account on this instance,
because it's Pro-gated and this instance has no license, so nothing could
ever have set it `true`. Technically correct, practically useless: on a
community-edition instance, *nobody* will ever show `true` there, so the
field can't distinguish anything.

**What the operator actually meant**, found by searching
`information_schema.columns` for every column named like `%admin%` rather
than assuming the one already found was the only one: `team_members.admin`
— a per-team-membership flag, **not** Pro-gated, and the mechanism that
actually governs project/task permissions on this kind of instance. A
live join across `team_members`/`users`/`teams` showed real accounts
genuinely are team admins (multiple teams, in one case), confirming this
is the practically meaningful field, not a hypothetical alternative.

**Fix, not a patch**: rather than swap one field for the other (which
would just relocate the same ambiguity — a future reader would still not
know which "admin" a bare `admins` field meant), both are kept, renamed to
be unambiguous on sight: `instance_admins` and `team_admin_of`. Every
identifier in the code (`_INSTANCE_ADMIN_QUERY` /`_TEAM_ADMIN_QUERY`,
`build_instance_admin_query_argv` / `build_team_admin_query_argv`,
`_parse_instance_admin_query` / `_parse_team_admin_query`) says which one
explicitly — no bare "admin" symbol left anywhere for a future edit to
misuse the way this one did.

`_parse_team_admin_query` only keeps rows where `tm.admin` is true (a
username with no team-admin roles simply doesn't appear in
`team_admin_of`, rather than appearing with an empty list) — a shorter,
more useful shape than mirroring `instance_admins`' every-row dict, since
"is this user an instance admin" has exactly one yes/no answer per user
while "which teams is this user admin of" is naturally a membership list,
often empty.

**Lesson worth stating plainly**: an AI-summarized web page's claim about
Vikunja's data model (quoted in #406's own PLAN.md section as "unverified
secondary evidence") turned out to be *directionally* right — is_admin
does exist independent of Pro — but incomplete in a way that mattered: it
said nothing about team-level admin at all, because that wasn't the
question asked of it. The fix wasn't reading more secondary sources more
carefully; it was going back to the live schema and asking a broader
question ("what columns are named like admin, anywhere") instead of
stopping at the first match.

## Bug: five subcommands never passed --config (opskit #410)

Found immediately after #408 shipped, while actually running `set-admin`
against a real instance for the first time: it failed with `ERROR:
service.publicurl is required when cors.enable is true` — not the
expected Pro-license error, because it never got that far.

`build_create_argv` and `build_list_argv` (the only two subcommands #402
and #404 actually live-verified) both pass `--config
{exec_cfg['config_path']}`. `build_update_argv`, `build_change_status_argv`,
`build_delete_argv`, `build_reset_password_argv`, and
`build_set_admin_argv` — every one of #404's additions — never did. Under
`sudo -u <exec_user>`, with no cwd or env pointing at the real config, the
vikunja binary falls back to its own default config discovery, which
finds nothing and fails before reaching whatever the command was actually
supposed to do.

**Root cause of the miss**: #404's tests asserted the *presence* of each
subcommand's own flags (`-u`, `-e`, `--enable`, `--now`, etc.) but never
cross-checked against the two working builders' shape, so a systematically
missing flag across five functions had nothing to catch it — one bad
example wasn't compared against the other one that got it right.

**Fix**: added `--config {shlex.quote(exec_cfg['config_path'])}` to all
five, in the same position `build_create_argv`/`build_list_argv` already
use (immediately after the subcommand name). Every existing test that
asserts an exact adjacent-substring argv shape for these five now
includes the `--config` segment explicitly, so this specific gap can't
silently reopen.

**Net effect this corrects**: 5 of this tool's 8 subcommands had never
actually worked against a real instance before this fix — only
`create`/`list` had been live-verified. `set-admin` was the first of the
five ever actually run live, and it's what surfaced this.
