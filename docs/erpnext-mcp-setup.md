# ERPNext MCP server with opencode

**TL;DR** create an ERPNext API key/secret, store the key and the *bare* secret
as two vault fields, fill in two gitignored files, unlock the vault, validate
with the launcher, register in `opencode.json`, restart opencode.

This runbook was validated live on 2026-08-30 against a production helpdesk:
follow it end-to-end and the server serves its tools from the first opencode
restart.

## Prerequisites

- An opskit checkout (<clone>/<pull> done, `make deps` has run so
  `mcp/erpnext-mcp-server.py` has its `mcp` dependency — see
  `docs/INSTALL.md`).
- The Bitwarden CLI: `npm install -g @bitwarden/cli` (`bw --version` works),
  and a vault you can unlock.

## Step 1 — create the API credentials in ERPNext

The MCP server authenticates with **token auth** against a low-privilege
service account — never the Administrator password, never a plaintext
password in config.

> **Who can create the keys: an ERPNext System Manager/Admin.** The
> "Generate New Key" control only exists for users with the right role. If
> your account lacks it (a standard Agent/helpdesk account can't see it),
> you need an admin to create the key/secret for the target user — that's
> the first place to check when "API Credentials" isn't there. Ask the site
> admin rather than assuming the UI is misconfigured.

In ERPNext, as the service account user (or your own user for a personal
token):

1. **User → API Credentials → Generate New Key.**
2. The screen shows the **api_key** and the **api_secret**.
   The `api_secret` is displayed **once** — do not close the dialog until it
   is stored.

> **Critical pitfall — store the bare secret, not `key:secret`.** The server
> builds `Authorization: token <api_key>:<api_secret>`. If the vault field
> holds the full token `key:secret`, that header becomes
> `token key:key:secret`, and every request **401s**. Verified live: the full
> token form returns 401, the bare-secret form returns 200.

## Step 2 — store the credentials in the vault

Create a vault item (e.g. "erpnext <env> api") with two custom fields:

| Field  | Value                  |
|--------|------------------------|
| `Key`  | the **api_key**        |
| `Secret` | the **bare api_secret** (no `key:` prefix) |

Record the item's ID (the vault's per-item UUID). You will reference it as
`item` in Step 4.

## Step 3 — `mcp/tenants.local.json`

Gitignored. Maps a tenant key to its helpdesk site:

```json
{
  "client1": {
    "site": "helpdesk.client1.example.org",
    "description": "Example client helpdesk"
  }
}
```

The tenant key you choose becomes the `<TENANT>` in the env var names of
Steps 4 and 8 (uppercased). The server falls back to a single example tenant
if this file is absent — you still need it for the real site.

## Step 4 — `mcp/vault-map.local.json`

Copy the tracked template and fill in the `erpnext` section. Both template
and these files are the contract between the launcher and the vault — the
real file is gitignored on purpose:

```bash
cp mcp/vault-map.example.json mcp/vault-map.local.json
```

```json
{
  "erpnext": {
    "ERPNEXT_API_KEY_CLIENT1": {
      "item": "<your vault item id>",
      "field": "Key"
    },
    "ERPNEXT_API_SECRET_CLIENT1": {
      "item": "<your vault item id>",
      "field": "Secret"
    }
  }
}
```

`field` names a custom field on the vault item — here `Key` and `Secret`,
exactly as you named them in Step 2. Fields may be `password | username |
totp | notes | <custom field name>`.

> Everything here is client-identifying (tenant names, vault identifiers).
> Both files stay gitignored and out of tracked commits — the repo's
> publication guards and client-data policy enforce this.

## Step 5 — unlock the vault for the launcher

The launcher resolves secrets at launch. Either source works; the **env var
wins** when both are present.

```bash
export BW_SESSION=$(bw unlock --raw)                    # this shell only
```

```bash
mkdir -p ~/.cache/opskit                                # persists across shells
(umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)
```

The second form is what a **detached** agent runtime (an opencode session
spawned outside your shell) reads. Write it inside `(umask 077; …)` — a plain
redirect leaves a live vault key group-readable. Export/establish the session
**before** starting opencode; servers read it at launch.

Diagnose a stale session: `bin/mcp-run.sh erpnext --check` prints exactly
which source is failing and how to refresh it.

## Step 6 — validate the launch path

```bash
bin/mcp-run.sh erpnext --check       # launcher path, venv, vault map, session
bin/mcp-call.py erpnext --probe      # boot the server, confirm it serves tools
```

- `--check` touches **no credentials** — it validates the launch path (server
  file, venv, `mcp` package, vault map, `bw` CLI, session state, declared
  secrets). Green output = would-launch.
- `--probe` **actually boots** the server and lists the tools it serves. This
  is the step that catches a server which launches but serves nothing — the
  silent-failure case where tools just never appear in the agent session.
  A healthy result is `OK erpnext 24 tools` (tool count varies as the server
  evolves).

Also handy, from any shell (no agent session needed):

```bash
bin/mcp-run.sh --list                # servers this repo provides
bin/mcp-call.py erpnext --list       # this server's tools
```

## Step 7 — register in opencode.json

Add an `mcp` entry to your user-level config
(`~/.config/opencode/opencode.json`) pointing at **the repo launcher**, not
the server script — the launcher resolves vault secrets, so no secret ever
sits in an agent config file (this was the pre-launcher failure mode: router
passwords in cleartext in `~/.config/opencode/opencode.json`).

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "erpnext": {
      "type": "local",
      "command": ["/absolute/path/to/opskit/bin/mcp-run.sh", "erpnext"]
    }
  }
}
```

- `command` is an array of strings — the old `command`/`args` string form is
  rejected by opencode.
- Use the **absolute** path to the launcher; runtime config is evaluated from
  wherever opencode starts.
- **Restart opencode.** Config is loaded once at startup — a running session
  keeps its already-loaded config and will not see the new server until the
  next launch.

## Step 8 — smoke test

From a fresh opencode session, or directly from a shell:

```bash
bin/mcp-call.py erpnext erpnext_list_tickets --arg tenant=client1 --arg limit=2
```

A JSON result with the tenant and a ticket list (or an empty list — the
important part is a live successful response, not a 401) means the wiring is
complete. From inside opencode the `erpnext_*` tools appear after the restart
in Step 7.

## Related

- `docs/INSTALL.md` §6.4 — all MCP servers this repo owns, plus migrating
  runtime config between workstations.
- `docs/DEV-GUIDE.md` — adding a *new* MCP server.
- `mcp/vault-map.example.json` — the field/vault contract for every server.
- `docs/credential-lifecycle.md` — rotating/revoking service-account tokens.