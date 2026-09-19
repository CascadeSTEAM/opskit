# MCP Bootstrap — Configuration, Session, and Verification

This doc covers the MCP bootstrap path: how MCP config files are generated, how the Bitwarden session is resolved, and how to verify the configuration is correct.

## Configuration Generation

`bin/gen-mcp-config.py` generates two config files from `environments/*/env.yml`:

- `tenants.local.json` — maps helpdesk tenant names to their site URLs
- `vault-map.local.json` — maps vault credential lookups for each env

The tool derives all values from `env.yml` — no per-file wiring needed. Adding an environment means adding `env.yml`; nothing else is edited.

Usage:

```bash
bin/gen-mcp-config.py --print-tenants          # tenants to stdout
bin/gen-mcp-config.py --print-vault-map        # vault-map to stdout
bin/gen-mcp-config.py --check                  # exit 1 if files differ
bin/gen-mcp-config.py --write                  # write both files (backs up existing)
```

Targets are `~/.mcp/tenants.local.json` and `~/.mcp/vault-map.local.json`, overridable via `ERPNEXT_TENANTS_FILE` and `OPSKIT_VAULT_MAP`.

## Vault Session Resolution

`bin/bw_session.py` resolves the Bitwarden session token from two sources:

1. `BW_SESSION` environment variable (wins if both present)
2. Session file at `~/.cache/opskit/bw-session` (or `BW_SESSION_FILE` override)

The file is checked for mode 600 — a session token is a live key to every secret in the vault, so an unverifiable guard that reports success is worse than no guard.

Usage:

```bash
bin/bw_session.py --source              # where a session would come from
bin/bw_session.py --check               # exit 0 if usable, 1 otherwise
bin/bw_session.py --token               # print the token for $(...) capture
bin/bw_session.py --refresh-hint        # how to refresh the session
```

## MCP Server Launch

`bin/mcp-run.sh` launches an MCP server with vault-resolved secrets. It reads `mcp/external-servers.json` for server definitions and resolves credentials from `vault-map.local.json`.

Usage:

```bash
bash bin/mcp-run.sh <server> --list       # list available servers
bash bin/mcp-run.sh <server> --check     # validate launch path
bash bin/mcp-run.sh <server>             # launch server with resolved secrets
```

## MCP Drift Detection

`bin/check-mcp-wiring.py` flags MCP entries wired to copies outside this repo (sibling checkout drift).

Usage:

```bash
bin/check-mcp-wiring.py                  # check all shipped servers
```

## Installation Flow

`install.sh` drives the whole bootstrap: it generates both config files from
your environment data and then starts every server for real to confirm it can
serve tools — not just that its launch path looks valid.

1. `bash install.sh --auto` — installs dependencies, links opskit CLI, generates
   `mcp/tenants.local.json` + `mcp/vault-map.local.json` (`opskit mcp setup`)
   and `~/.mikromcp/routers.yaml`, then probes every MCP server
   (`bin/mcp-call.py --probe`). Servers that cannot serve tools are named in
   the probe output; a locked/absent vault or placeholder vault item IDs only
   warn — they do not fail the install.
2. `opskit env <env>` — switch to environment (adds its helpdesk tenant to the
   generated config on the next run).
3. Re-generate when `env.yml` changes: `opskit mcp setup` (and
   `bin/gen-mikromcp-config.py --write` when device datasets change).
4. Fill in real vault item IDs in `mcp/vault-map.local.json` (the generator
   emits placeholders), then `bw unlock` and verify with
   `bin/mcp-call.py --probe` or `opskit mcp verify`.

`bash install.sh --check` is the read-only preflight: it reports config drift
against `env.yml` and the datasets, and runs the same live probe — all without
changing anything.

## `opskit mcp` Commands

### `opskit mcp status`

Show MCP config status — tenants, vault map entries, and server reachability.

```bash
opskit mcp status
opskit mcp status --json
```

### `opskit mcp setup`

Generate MCP config files from env.yml. Backs up existing files.

```bash
opskit mcp setup
```

### `opskit mcp check`

Check MCP config structure without vault contact.

```bash
opskit mcp check
```

### `opskit mcp verify`

Verify MCP config + vault session state. Optionally verify a specific server.

```bash
opskit mcp verify
opskit mcp verify --server erpnext
```

## Reference

- `docs/INSTALL.md` — full installation guide
- `docs/erpnext-mcp-setup.md` — ERPNext helpdesk MCP setup
- `docs/proxmox-mcp-setup.md` — Proxmox MCP setup
