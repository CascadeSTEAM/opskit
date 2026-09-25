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
   `https://todo.bellinghammakerspace.org` named a real environment's domain
   directly in a file destined for the committed skill tree — a Core Rule
   violation ("never hardcode environment names, hostnames, or subnets;
   discover them at runtime") and adjacent to the Client-Data-Isolation hard
   rule. Fixed by moving the base URL into `environments/<env>/env.yml`
   (gitignored), the same place `frappe:` config already lives.
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

- **`mcp/vikunja-mcp-server.py`** (new, in-repo) — one tool:
  `vikunja_create_task(env, title, description="", project=None)`.
  - Loads `environments/<env>/env.yml`'s `vikunja:` block for `base_url` and
    a `default_project`.
  - Resolves the target project via `GET /api/v1/projects`: exact name match
    against `project` (or `default_project` if `project` is omitted). Zero or
    multiple matches → return an error string listing the candidates; the
    caller (agent) surfaces that to the operator instead of guessing.
  - Creates the task with `PUT /api/v1/projects/{id}/tasks`,
    body `{"title": title, "description": description}`.
  - Returns `{"task": {...}, "url": f"{base_url}/tasks/{id}"}` as JSON, or
    `{"error": "..."}` on failure — same convention as
    `erpnext_create_ticket`.
  - Auth: `Authorization: Bearer $VIKUNJA_<ENV>_TOKEN`, read from the process
    environment only (see Credentials). Never logs the token; error messages
    quote the API's own JSON body, which does not echo the token back.
- **`.opencode/skills/vikunja-ticket/SKILL.md`** (this directory) — documents
  `bin/mcp-call.py vikunja vikunja_create_task --arg env=<env> --str title="..." --str description="..."`
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
    "VIKUNJA_<ENV>_TOKEN": {"item": "<vault item id>", "field": "password"}
  }
  ```
  (env-scoped variable name, matching `TECHNITIUM_<SITE>_PASS` /
  `ERPNEXT_API_KEY_<TENANT>` — this repo is multi-environment, so a bare
  `VIKUNJA_TOKEN` would silently assume there is only ever one instance.)
- The MCP server resolves this normally at launch, like every other in-repo
  server — no special-casing needed once the file exists.
- For the curl fallback specifically (no MCP runtime available at all), pull
  the same secret without a file: `eval "$(bin/mcp-run.sh vikunja --print-env)"`
  immediately before the call, in the same shell invocation that uses it.
  Never redirect it to a file; never echo it.
- **Token scope**: create a Vikunja API token scoped to task creation and
  project read only (Vikunja supports per-token route scoping) — not a full
  personal-account token. Name the vault item so its purpose and scope are
  obvious from the name alone, per `docs/credential-lifecycle.md`.
- Precondition, not a blocker: vault must be unlocked. If `bin/mcp-run.sh
  vikunja --check` reports it locked, use the `bwunlock` skill — do not
  attempt `bw unlock` directly and do not ask for the master password.

## Configuration (`environments/<env>/env.yml`)

```yaml
vikunja:
  base_url: https://<instance-host>          # gitignored layer only
  default_project: <project name>
```

No hostname, project id, or instance name is ever hardcoded in
`mcp/vikunja-mcp-server.py` or the skill file — both read this block.

## Fallback: raw curl (only if `bin/mcp-call.py` truly cannot run)

```bash
eval "$(bin/mcp-run.sh vikunja --print-env)"   # exports VIKUNJA_<ENV>_TOKEN, nothing written to disk

BASE_URL="<from environments/$ACTIVE_ENV/env.yml: vikunja.base_url>"
PROJECT_ID="<resolved from GET /api/v1/projects>"

BODY=$(jq -n --arg t "$TITLE" --arg d "$DESC" '{title:$t, description:$d}')
RESPONSE=$(curl -sS -w '\n%{http_code}' \
  --config <(printf 'header = "Authorization: Bearer %s"\n' "$VIKUNJA_TOKEN") \
  -H "Content-Type: application/json" \
  -X PUT "$BASE_URL/api/v1/projects/$PROJECT_ID/tasks" \
  -d "$BODY")
STATUS="${RESPONSE##*$'\n'}"
JSON="${RESPONSE%$'\n'*}"
```

- `--config` with a process-substitution here-string keeps the token off
  argv; `-w '%{http_code}'` is what makes the error table below possible.
- `jq -n --arg` was already correct in the original draft — arbitrary title/
  description text goes through JSON string escaping, not shell/string
  interpolation. Keep it.
- Body is only `{title, description}`. Title required; description optional.
- **PUT, not POST** (POST 404s on this API) — still unverified against the
  live instance; confirm with the smoke test before relying on it.

## Error handling

| `$STATUS` | Meaning | Action |
|---|---|---|
| 2xx | Created | Parse `$JSON` for `id`, report `$BASE_URL/tasks/<id>` |
| 401 | Token invalid/expired/wrong scope | Report; do not retry |
| 400 | Bad request | Echo the API's field errors from `$JSON` |
| 404 (on the tasks call) | Project id stale/wrong | Report; do not retry |
| 5xx | Server error | Retry once **only if** the failure was connect-level (curl exit 6/7/28) — a 5xx that produced a body already reached the server; retrying risks a duplicate task, so report instead |

## Verification

1. Smoke test: `curl -sSI --config <(...) "$BASE_URL/api/v1/projects"` → 200
   proves token + reachability, before anything is created.
2. Create one real task with a `[TEST]`-prefixed title (or in a project
   designated for this purpose) and confirm the returned URL opens. Leaving
   it in place is fine — deletion is explicitly out of scope (below); this
   keeps the smoke test from needing capabilities the skill doesn't have.
3. Confirm the create-task response shape matches what step 1 of Architecture
   assumes (`id` field present) — this and the PUT-vs-POST behavior are the
   two facts in this plan taken from memory rather than a live call.

## Deliberately out of scope for v1

No assignee/label/due-date resolution, no dedup search, no YAML spec, no
editing/deleting existing tasks, no multi-project routing beyond
name-matching. Add only if a real need shows up.

## Remaining open decisions

1. Which vault item is the source of truth for the Vikunja token, and its
   exact scope — create the item (or confirm the existing "Vikunja —
   netyeti" one is fit for reuse as a scoped service credential rather than a
   personal token) before writing `vault-map.local.json`.
2. Confirm the API shape (PUT create, `id` in the response) with the smoke
   test in step 3 above before the MCP tool ships.
