---
name: technitium-dns
description: "Reach the Technitium DNS/DHCP MCP server from any agent runtime that does not hold its native tool schema — Claude Code and every OpenCode/Crush agent without direct technitium_* access — through bin/mcp-call.py technitium, the same vault-resolved launcher the native tools use. Use for: technitium, dns, dhcp, dns record, dns zone, dhcp lease, dhcp scope"
mode: skill
triggers: technitium,dns,dhcp,dns record,dns zone,dhcp lease,dhcp scope,dns server
---

# technitium-dns

> Claude Code has no MCP servers configured at all, and no runtime other than
> the ones that carry `technitium_*` natively can reach Technitium directly.
> `bin/mcp-call.py technitium` reaches the same vault-resolved server through
> a shell call instead — same credentials, same launcher as the native tools
> (`bin/mcp-run.sh`), so there is exactly one place this ever drifts from.

## Quick Reference

| Need | Command |
|---|---|
| Can the server serve right now? | `bin/mcp-call.py technitium --probe` |
| Every tool with its schema | `bin/mcp-call.py technitium --list` |
| List DNS zones | `bin/mcp-call.py technitium dns_list_zones` |
| List/compare DNS servers | `bin/mcp-call.py technitium dns_list_servers` · `dns_compare` |
| Read records in a zone | `bin/mcp-call.py technitium dns_get_records --arg zone=<zone>` |
| Add/change a record | `bin/mcp-call.py technitium dns_update_record '{"zone":"<zone>", ...}'` |
| Delete a record | `bin/mcp-call.py technitium dns_delete_record --arg zone=<zone> --arg name=<name> --arg type=<type>` |
| Resync a zone | `bin/mcp-call.py technitium dns_resync_zone --arg zone=<zone>` |
| Flush the local cache | `bin/mcp-call.py technitium dns_flush_local_cache` |
| DHCP scopes/leases | `bin/mcp-call.py technitium dhcp_list_scopes` · `dhcp_get_scope --arg name=<scope>` · `dhcp_list_leases --arg scope=<scope>` |
| DHCP reservations | `bin/mcp-call.py technitium dhcp_add_reservation '{...}'` · `dhcp_remove_reservation --arg scope=<scope> --arg mac=<mac>` |
| DHCP scope DNS settings | `bin/mcp-call.py technitium dhcp_update_scope_dns '{...}'` |
| Clear DHCP static routes | `bin/mcp-call.py technitium dhcp_clear_static_routes --arg scope=<scope>` |

`--arg` coerces JSON scalars (numbers, `true`/`false`, `null`); bare words
stay strings. Use `--str k=v` for a value that must stay a string even if it
looks numeric. Output is the tool's structured JSON result.

## Steps

1. This repo tracks multiple Technitium instances by environment (see
   `mcp/vault-map.local.json`'s `technitium` keys) — confirm the active
   environment (`opskit env`) matches the instance you mean to change before
   any write.
2. **Read before you write**: `dns_list_zones` / `dns_get_records` first, so
   the change is against known current state, not a guess.
3. Writes to production DNS are felt everywhere immediately — there is no
   staging tier. Prefer the smallest change that accomplishes the task, and
   verify after with a re-read (`dns_get_records`, `dhcp_list_leases`).
4. Report the exact record/scope changed and its new state back to the
   operator.

## Failure handling

- "vault is LOCKED" / no `BW_SESSION`: ask the operator to refresh it
  (`bwunlock` skill) — never run `bw unlock` yourself.
- `--probe` fails with a connection error: check the environment's Technitium
  host is reachable (`check-connectivity` skill) before assuming the server
  itself is broken.
- Failure output may quote server stderr containing credentials: read it,
  act on it, never paste it into an issue, PR, or public channel.

## Related

- `bin/mcp-call.py` — the one-shot MCP client (opskit #110); `bin/mcp-run.sh`
  launches the server
- `mcp/technitium-mcp-server.py` — the server implementation
- `docs/mcp-bootstrap.md` — MCP config generation, vault session, and
  `opskit mcp` commands
- `routeros` skill — the same bridge pattern, first built for mikromcp
