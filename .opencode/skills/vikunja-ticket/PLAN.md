# Plan: Vikunja ticket-generation skill

Goal: let the agent create one task in a Vikunja instance from a title +
description, and report the task URL. Minimal surface area, but built on the
same credential and integration conventions every other OpsKit integration
uses — not a one-off shortcut.

## Review of the original draft

The original draft (`skills/vikunja-ticket/PLAN.md`) got the operation right
(PUT to create, report the URL, discover the project instead of hardcoding an
id) but broke several hard rules of this repo to get to "no app code, just
curl." Each is a real defect, not a style nit:

1. **Wrong skill tree.** It lived under `skills/vikunja-ticket/`. This repo
   has exactly one skill tree, `.opencode/skills/` — a second tracked `skills/`
   directory existed until #131 and caused every shared skill to drift
   between harnesses. Fixed by moving this file here.
2. **Plaintext token on disk, permanently.** "Write the token to a file once,
   never go back to the vault" is precisely what
   `.opencode/rules/no-plaintext-creds.md` and AGENTS.md's "Credentials
   referenced by vault name only — never plaintext" forbid. It also has no
   rotation or revocation story: a compromised or expired token sits
   unnoticed forever, and there's no lifecycle entry for it
   (`docs/credential-lifecycle.md`). Fixed by resolving the token from the
   vault at run time, every run, via the same `bin/mcp-run.sh --print-env`
   path every other integration uses (see Credentials below).
3. **Hardcoded production hostname in a tracked file.**
   The original draft's core command named a real client environment's Vikunja
   domain directly in a file destined for the committed skill tree — a Core Rule
   violation ("never hardcode environment names, hostnames, or subnets;
   discover them at runtime") and adjacent to the Client-Data-Isolation hard
   rule. Fixed by moving the base URL into a gitignored tenant config file
   (`mcp/tenants-vikunja.local.json`), the same convention `erpnext`/
   `technitium` already use for their own instance hostnames.
4. **"No app code" collided with Development Principle #2.** Vikunja task
   creation is application-record state (API CRUD inside a hosted app), and
   the principle is explicit that the vehicle for that is an MCP tool, not a
   loose script. A curl one-liner also can't be reused by `@skill-builder`'s
   registration conventions or bridged through `bin/mcp-call.py` the way
   every comparable integration (technitium, proxmox, erpnext) is. Fixed by
   building the smallest possible real MCP tool (one function) instead of a
   documented shell command — see Architecture. This is the biggest change
   from the original draft; flagging it plainly rather than quietly expanding
   scope.
5. **The documented curl command couldn't implement its own error-handling
   section.** `curl -sS ... -X PUT ...` discards the HTTP status code
   entirely, but the plan's error table (401/400/404/5xx) depends on reading
   it. Fixed in the fallback command below by capturing status separately.
6. **Token passed on argv.** `-H "Authorization: Bearer $VIKUNJA_TOKEN"`
   expands the live token into the process's argv, visible to any local user
   via `ps`/`/proc/<pid>/cmdline` — the same class of exposure `bwunlock`
   already treats as unacceptable for the vault master password. Fixed by
   feeding the header to curl over stdin via `--config -`.
7. **Retry-after-ambiguous-failure risks duplicate tickets.** "5xx → one
   retry" is unsafe if the first request reached the server and only the
   response was lost — a retry then creates a second task. Fixed by scoping
   retries to connect-level failures only (curl exit codes 6/7/28), never to
   a request that got a server response.
8. **No least-privilege requirement on the token.** Every other integration
   in this repo (erpnext, proxmox) insists on a scoped service-account
   credential, never an admin/personal one. The original plan didn't say
   this. Fixed — see Credentials.
9. **Self-contradiction on "nothing interactive."** The goal says
   non-interactive, but Target Project resolution says to ask the user on an
   ambiguous match. Kept the "ask on ambiguity" behavior (guessing a project
   id is worse) and reworded the goal to mean *no additional prompts beyond
   title/description*, not *never ask anything*.
10. **"Blocker: we cannot bootstrap" wasn't a plan, it was giving up.** Per
    standing guidance, a locked vault is never a dead end — it's "ask the
    operator to unlock it," using the existing `bwunlock` skill. Removed the
    Blocker section; the precondition is just "vault unlocked," same as every
    other integration.

## Architecture

Same shape as `technitium-dns` / `proxmox-cli` / `routeros`: a real MCP
server owns the API call and the credential, and a thin skill documents how
to reach it from any runtime.

- **`mcp/vikunja-mcp-server.py`** (new, in-repo — built, see the file itself
  for the authoritative interface) — one tool:
  `vikunja_create_task(tenant, title, description="", project=None)`.
  - Loads `mcp/tenants-vikunja.local.json` (gitignored; example fallback
    embedded) for each tenant's `base_url` and `default_project` — same
    tenant-file convention as `erpnext`/`technitium`, not
    `environments/<env>/env.yml` (that path is for non-MCP scripts like
    `frappe-exec.py`; MCP servers keep their own tenant config).
  - Resolves the target project via `GET /api/v1/projects`: exact name match
    against `project` (or `default_project` if `project` is omitted). Zero or
    multiple matches → an error naming the candidates; never guesses.
  - Creates the task with `PUT /api/v1/projects/{id}/tasks`,
    body `{"title": title, "description": description}`.
  - Returns `{"tenant": ..., "task": {...}, "url": "<base_url>/tasks/<id>"}`
    as JSON, or `{"error": "..."}` on failure — same convention as
    `erpnext_create_ticket`.
  - Auth: `Authorization: Bearer <token>`, read from the process environment
    only (see Credentials). Never logs the token; error messages quote the
    API's own JSON body, which does not echo the token back.
- **`.opencode/skills/vikunja-ticket/SKILL.md`** (this directory) — documents
  `bin/mcp-call.py vikunja vikunja_create_task --arg tenant=<tenant> --str title="..." --str description="..."`
  for any runtime without native `vikunja_*` tool access (Claude Code, and
  any OpenCode/Crush agent the server isn't wired into) — build this file
  with `@skill-builder` so frontmatter/registration stay consistent with
  every other skill.
- **Native path**: once wired into `opencode.json`, agents holding the
  `vikunja_*` schema natively call the tool directly, same as the other
  domain servers.
- **`vikunja-mcp` (external, third-party)**: if a maintained Vikunja MCP
  server is ever installed, register it in `mcp/external-servers.json`
  (command + install hint, no hostnames — see that file's existing entries)
  and retire `mcp/vikunja-mcp-server.py` in its favor. Not done now because
  it isn't installed; no need to block v1 on it.

## Credentials

- Vault stays the single source of truth. Add to `mcp/vault-map.local.json`:
  ```
  "vikunja": {
    "VIKUNJA_<TENANT>_TOKEN": {"item": "<vault item id>", "field": "password"}
  }
  ```
  (tenant-scoped variable name, matching `TECHNITIUM_<SITE>_PASS` — this repo
  is multi-tenant, so a bare `VIKUNJA_TOKEN` would silently assume there is
  only ever one instance; the server does accept it as a fallback for a
  single-tenant setup, same as `ERPNEXT_API_KEY`/`ERPNEXT_API_SECRET`.)
- `bin/mcp-run.sh vikunja` (or `--print-env`/`--check`) resolves this
  normally at launch, like every other in-repo server — no special-casing
  needed once the file exists.
- Never written to disk anywhere, ever — resolved into the process
  environment at launch only.
- **Token scope**: create a Vikunja API token scoped to task creation and
  project read only (Vikunja supports per-token route scoping) — not a full
  personal-account token. Name the vault item so its purpose and scope are
  obvious from the name alone, per `docs/credential-lifecycle.md`.
- Precondition, not a blocker: vault must be unlocked. If `bin/mcp-run.sh
  vikunja --check` reports it locked, use the `bwunlock` skill — do not
  attempt `bw unlock` directly and do not ask for the master password.

## Tenant configuration (`mcp/tenants-vikunja.local.json`, gitignored)

```json
{
  "client1": {
    "base_url": "https://<instance-host>",
    "default_project": "<project name>"
  }
}
```

No hostname, project id, or instance name is ever hardcoded in
`mcp/vikunja-mcp-server.py` or the skill file — both read this file (the
committed copy of the server embeds only the doc-range example above as its
fallback, so the module still imports cleanly with no local config present).
Override the path with `VIKUNJA_TENANTS_FILE` (this is how the test suite
stays independent of whatever a developer has locally).

## Error handling

`vikunja_create_task` never raises out to the caller — every failure comes
back as `{"error": "..."}` JSON:

| Situation | Result |
|---|---|
| Unknown tenant | Plain string naming the valid tenants (matches `erpnext_create_ticket`'s convention) |
| Empty/missing title | `{"error": "title is required"}` |
| No project matches `project`/`default_project` | `{"error": "no project named '<x>' found. Available: ..."}` — never guesses |
| Multiple projects share that title | `{"error": "multiple projects named '<x>' found (ids: ...)"}` — task is **not** created |
| Token env var missing | `{"error": "VIKUNJA_<TENANT>_TOKEN (or VIKUNJA_TOKEN) not set. ..."}` |
| Vikunja API returns an HTTP error | `{"error": "Vikunja API error (<status>): <API's own JSON body>"}` |

No automatic retry on a 5xx: a response that reached the server may mean the
task was already created, so retrying risks a duplicate. The agent reports
the failure and lets the operator decide, rather than guessing.

## Verification

1. `bin/mcp-run.sh vikunja --check` → confirms the launch path (venv, vault
   session, map entries) before anything is created.
2. `python3 mcp/vikunja-mcp-server.py --test` (with the token exported) →
   creates one real task titled `[TEST] MCP smoke test - please ignore` and
   prints the resulting URL. Leaving it in place is fine — deletion is
   explicitly out of scope (below); this keeps verification from needing
   capabilities the tool doesn't have.
3. Confirm the create-task response shape matches what the client assumes
   (`id` field present) — this and the PUT-vs-POST behavior are the two facts
   in this plan taken from memory rather than a live call before step 2.

## Deliberately out of scope for v1

No dedup search, no YAML spec, no editing/deleting existing tasks, no
multi-project routing beyond name-matching, no relative reminders (only
absolute ISO8601 timestamps). (Priority/due-date/assignees/labels/
reminders/recurrence were originally on this list too; added in #396 and
#400 once a real need showed up.) Add more only on the same basis.

## Extension: priority, due date, assignees, labels (opskit #396)

Added after v1 shipped, at the operator's request, once live testing showed
the basic create call working. API shapes below were verified live against
a real Vikunja instance, not guessed:

- `priority` (int, 0=Unset..5=DO NOW) and `due_date` (ISO8601 string) are
  plain fields on the same create body — no extra call.
- `assignees` (comma-separated usernames) resolve via
  `GET /api/v1/users?s=<name>` (substring search — filtered to an exact
  `username` match), then `PUT /api/v1/tasks/{id}/assignees`
  (`{"user_id": <id>}`), once per name.
- `labels` (comma-separated names) resolve via `GET /api/v1/labels`
  (global list), same exact-match/no-guess convention as project
  resolution, then `PUT /api/v1/tasks/{id}/labels` (`{"label_id": <id>}`).
- Resolution happens **before** the task is created (a typo must not create
  a half-configured task); attaching happens **after** (these endpoints need
  a real task id). If an attach call itself fails post-creation, the result
  is a success envelope with a `warnings` list, never a bare error — the
  task is real, and reporting only an error risks a duplicate-creating
  retry, the same failure class the original create call already guards
  against.

## Extension: reminders and recurrence (opskit #400)

Verified live (Vikunja v2.6.0) same as the above:

- `reminders`: a list of `{"reminder": "<ISO8601>"}` objects, plain field on
  the create body like `priority`/`due_date` — no extra call, no separate
  resolution step (unlike assignees/labels). Only absolute timestamps are
  supported; Vikunja's relative-reminder shape (`relative_period`/
  `relative_to`) is deferred until a real need shows up.
- `repeat_after` (seconds) and `repeat_mode` (0=simple interval, 1=monthly,
  2=from completion date) are also plain create-body fields. Each is
  range/sign-validated independently before any network call, same
  convention as `priority` — no invented cross-field rule requiring one
  when the other is set; Vikunja's own "does not repeat" default applies
  when both are omitted.

## Resolved decisions (were open before the first live test)

1. Vault item: the existing "Vikunja — netyeti" item's bot-scoped field was
   tried first and 403'd on task creation (valid token, insufficient
   project permission) even after an attempted fix; the personal-account
   field (`API Token (self)`) is wired in for now as a working stand-in.
   **Still open**: get the bot account's write permission actually fixed and
   swap back — running on a personal token is against this plan's own
   least-privilege principle (see flaw review, point 8).
2. API shape confirmed live: PUT creates, response includes `id`, base URL
   + `/tasks/<id>` is a working link.
