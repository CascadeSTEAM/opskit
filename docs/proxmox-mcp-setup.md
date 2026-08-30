# Proxmox MCP server with opencode

**TL;DR** create a per-operator Proxmox API token on a dedicated service user,
grant a read-only role that includes `Sys.Audit`, store the full identity
(`user@realm!tokenname`) and the secret as two vault fields, fill in two
gitignored files, unlock the vault, validate with the launcher, register in
`opencode.jsonc` (with an `environment` block to pick the cluster), restart
opencode.

This runbook was validated live on 2026-08-30 against a production Proxmox
clustered environment: follow it and the server serves its tools from the
first opencode restart.

## Prerequisites

- An opskit checkout (`<clone>/<pull>` done, `make deps` has run so the
  `mcp` package is importable in the repo venv — see `docs/INSTALL.md`).
- The Bitwarden CLI: `npm install -g @bitwarden/cli` (`bw --version` works),
  and a vault you can unlock.

## Step 1 — create the API token in Proxmox

The MCP server authenticates with **token auth** against a low-privilege
service account — never the `root` password, never a plaintext password in
config.

> **Token identity format.** The server needs the full identity
> `user@realm!tokenname` (e.g. `opskit-mcp@pve!lili`). The `!` separates the
> token name from the user, and is **mandatory**: the wrapper refuses an
> identity without one rather than guess (`split_identity()` in
> `mcp/proxmox-mcp-server.py`). Passing the combined value as a plain username
> yields a malformed `PVEAPIToken` header and a 401 that reads as a wrong
> credential.

1. **Create a dedicated service user** — Datacenter → Permissions → Users →
   Add. Do not reuse an administrator. Example: `opskit-mcp@pve`.
2. **Grant the user a role at the datacenter root** (`/`) so it can read
   across the cluster. **PVEAuditor is read-only but not enough for
   everything**: `get_cluster_status` needs `Sys.Audit`, which PVEAuditor
   does *not* grant — a `PVEAuditor`-only token 403s on that tool even though
   node/VM/container listings work. Create a custom role (Permissions →
   Roles → Add) named e.g. `PVEAuditorPlus` with exactly:
   - `Sys.Audit`
   - `VM.Audit`
   - `Datastore.Audit`
   - `Pool.Audit`
   Then grant that role to the user on `/`.
3. **Create the token** — Datacenter → Permissions → API Tokens → Add,
   select the service user, and give the token a **per-operator name**:
   `mcp` (matches the shared convention) or your short name
   (e.g. `lili`) for attribution — the full identity is
   `opskit-mcp@pve!<tokenname>`.
4. **Privilege Separation = ON.** With it on, the token's effective rights
   are the **intersection** of the user's roles and the token's own roles —
   grant the same read-only role to the **token as well** (the token appears
   as `opskit-mcp@pve!<tokenname>` in the permission picker). If you grant
   the role only to the user, read calls silently return empty or 403.
5. **Copy the token secret** (shown once) and store it immediately — see
   Step 2.

> **Write permissions.** Everything above is read-only. Only add write-capable
> roles (e.g. `PVEVMUser`, `PVEAdmin`) deliberately and document who/what uses
> them. The least-privilege default is what the MCP toolset is scoped for.

## Step 2 — store the token in the vault

Create a vault item (e.g. "proxmox <env> api") with:

| Field  | Value                                          |
|--------|------------------------------------------------|
| `username` | the **full identity** `opskit-mcp@pve!lili` |
| `password` | the **token secret**                        |

The username field carries the token *identity*, not a login — this is what
makes the `!` matter. Record the item's UUID; you will reference it as `item`
in Step 4.

## Step 3 — `mcp/tenants-proxmox.local.json`

Gitignored (hostnames, addresses and environment names are client/network
data). Maps an environment key to its Proxmox node:

```json
{
  "client1": {
    "host": "pve.client1.example.org",
    "port": 443,
    "verify_ssl": true,
    "env_token_identity": "PROXMOX_CLIENT1_TOKEN_IDENTITY",
    "env_token_value": "PROXMOX_CLIENT1_TOKEN_VALUE",
    "description": "Example environment — replace with your own."
  }
}
```

- `host` — the Proxmox node or a cluster VIP fronting it, reachable from the
  workstation (usually in-tunnel).
- `port` — default 8006. Use **443** when the API is fronted by a reverse
  proxy / load balancer with TLS termination.
- `verify_ssl` — default false (Proxmox ships a self-signed certificate).
  Set **true** where a trusted public-CA cert is in front (e.g. a
  Let's Encrypt VIP). Prefer true when you can: the upstream server refuses
  `verify_ssl=false` unless `PROXMOX_DEV_MODE=true` is set, which is a
  dev-only escape hatch — a public-CA front door avoids needing it.
- `env_token_identity` / `env_token_value` — the branch-scoped env var names
  the server reads, per environment (these become `PROXMOX_<ENV>_TOKEN_IDENTITY`
  / `_VALUE` in Step 4).

See `mcp/tenants-proxmox.example.json` for the full key contract.

## Step 4 — `mcp/vault-map.local.json`

Copy the tracked template and fill in each environment's `proxmox` section.
Real vault identifiers stay in the gitignored file:

```bash
cp mcp/vault-map.example.json mcp/vault-map.local.json
```

```json
{
  "proxmox": {
    "PROXMOX_CLIENT1_TOKEN_IDENTITY": {
      "item": "<your vault item id>",
      "field": "username"
    },
    "PROXMOX_CLIENT1_TOKEN_VALUE": {
      "item": "<your vault item id>",
      "field": "password"
    }
  }
}
```

The identity comes from the item's `username` field and the value from its
`password` field — the server splits the identity itself, so the map stays
one-field-to-one-variable with no transforms.

> Everything here is client-identifying (nodes, vault identifiers). Both
> files stay gitignored and out of tracked commits — the repo's publication
> guards and client-data policy enforce this.

## Step 5 — unlock the vault for the launcher

Identical to every other MCP server; either source works, env var wins:

```bash
export BW_SESSION=$(bw unlock --raw)                    # this shell only

mkdir -p ~/.cache/opskit                                # persists across shells
(umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)
```

> The session expires when the vault auto-locks. If proxmox tools vanish "for
> no reason", refresh the session file first (diagnose with
> `bin/mcp-run.sh proxmox --check`), then restart opencode — do not chase the
> config.

## Step 6 — validate the launch path and pick the cluster

```bash
bin/mcp-run.sh proxmox --check       # launcher path, venv, vault map, session
PROXMOX_ENV=client1 bin/mcp-call.py proxmox --list   # boot server, list tools
PROXMOX_ENV=cluster1 bin/mcp-call.py proxmox get_cluster_status   # live call
```

The environment is selected by **`PROXMOX_ENV`, which wins over `ACTIVE_ENV`**
from `.env` (see `active_env()` in `mcp/proxmox-mcp-server.py`). Set
`PROXMOX_ENV=<env>` to point at a specific cluster regardless of the
session's active environment — this is what lets one opencode config switch
clusters without `switch-env.sh`.

## Step 7 — register in opencode.json/.jsonc

Add an `mcp` entry to your user-level config
(`~/.config/opencode/opencode.json` **or** `opencode.jsonc`), pointing at the
repo launcher. Use the **`environment` block to pin the cluster**:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "proxmox": {
      "type": "local",
      "command": ["/absolute/path/to/opskit/bin/mcp-run.sh", "proxmox"],
      // Switch clusters by editing PROXMOX_ENV, then restart opencode.
      "environment": {
        "PROXMOX_ENV": "cluster1"
      }
    }
  }
}
```

- `command` is an array of strings; the old string form is rejected.
- Use the **absolute** path to the launcher.
- `environment` maps `PROXMOX_ENV` → the cluster key from
  Step 3/Step 4. To point at a different cluster later, edit one value and
  restart opencode — no secret, no `ACTIVE_ENV` change.
- The file is JSONC (comments allowed), but **`bin/check-mcp-wiring.py`
  currently parses strict JSON and will reject comments before the JSONC
  parsing gap is fixed (opskit #288).**
- **Restart opencode** — config is loaded at startup only.

## Step 8 — smoke test

```bash
PROXMOX_ENV=cluster1 bin/mcp-call.py proxmox get_cluster_status
```

A cluster summary (name, quorum, node count) means the wiring is complete. A
`403 Permission check failed (/, Sys.Audit)` means the token's role is missing
`Sys.Audit` — go back to Step 1 and grant the custom role (to **both** the
user and the token). After the Step 7 restart, the `proxmox_*` tools appear
in the agent session.

## Related

- `docs/erpnext-mcp-setup.md` — the sibling ERPNext server runbook; same
  vault/launcher pattern.
- `docs/INSTALL.md` §6.4 — all MCP servers this repo owns, migrating runtime
  config between workstations.
- `docs/DEV-GUIDE.md` — adding a *new* MCP server.
- `mcp/vault-map.example.json` — the field/vault contract for every server.
- `docs/credential-lifecycle.md` — rotating/revoking service-account tokens.