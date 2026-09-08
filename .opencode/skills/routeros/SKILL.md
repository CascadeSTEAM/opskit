---
name: routeros
description: "Reach MikroTik RouterOS and SwOS devices from any agent runtime that does not hold mikromcp's tool schemas — Claude Code, Crush, and every OpenCode agent except @mikrotik — through bin/mcp-call.py mikromcp, the same vault-resolved launcher the MCP server uses. Use for: mikrotik, routeros, router, switch, capsman, wifi, mikromcp"
mode: skill
triggers: mikrotik,routeros,mikromcp,capsman,router,switch,wifi,swos
---

# routeros

> mikromcp's tool schemas cost tens of thousands of tokens per request, so no
> runtime carries them always-on (#314). OpenCode's `@mikrotik` keeps the native
> `mikromcp_*` tools; everywhere else, reach the same server via `bin/mcp-call.py`.

## Quick Reference

| Need | Command |
|---|---|
| Can the server serve right now? | `bin/mcp-call.py mikromcp --probe` |
| Every tool with its schema | `bin/mcp-call.py mikromcp --list` |
| Call with no arguments | `bin/mcp-call.py mikromcp list_routers` |
| Call with arguments | `bin/mcp-call.py mikromcp get_system_status --arg routerId=<id>` |
| JSON arguments | `bin/mcp-call.py mikromcp run_command '{"routerId":"<id>","command":"/system/resource/print"}'` |

Most tools take `routerId` (omit it for the default router); `list_routers`
shows the IDs. `--arg` coerces digit-only values to numbers — use `--str k=v`
for an ID that must stay a string. Output is the tool's structured result as JSON.

## Tools You Will Reach For Most

- **Read:** `get_system_status`, `list_interfaces`, `list_dhcp_leases`,
  `list_firewall_rules`, `list_routes`, `list_wifi_clients`, `list_neighbors`,
  `get_log`, `check_router_health`, `list_routers`, `get_swos_status` (SwOS)
- **Diagnose:** `ping --arg address=…`, `traceroute --arg address=…`,
  `torch --arg interface=…`
- **Change:** every `manage_*` tool takes `action` (add | remove | enable |
  disable | update) plus the object's key — e.g. `manage_firewall_rule`,
  `manage_ip_address`, `manage_dns_entry`, `manage_wifi_interface`
- **Safety:** `plan_changes` (dry-runs a step list) → `apply_plan` →
  `rollback_change --arg journalId=…`; `create_backup` / `export_config` first
- **Fan-out:** `bulk_execute '{"toolName":"get_system_status","params":{},"tags":["…"]}'`

## Key Rules

- AGENTS.md's announce-toolset-and-wait rule applies to every call here.
- Never SSH or relay-shell to MikroTik gear — denied by design. `run_command`
  goes through mikromcp and is the sanctioned console path.
- Writes still belong in a playbook (IaC rule); mcp-call is for reads,
  diagnosis and emergency changes that then get codified.
- Needs an unlocked vault session in the launching shell. On "vault is LOCKED"
  ask the operator to refresh it — never run `bw unlock` yourself.
- Failure output may quote server stderr containing credentials: read it, act
  on it, never paste it into an issue or PR.

## Related

- `bin/mcp-call.py` — the one-shot MCP client (opskit #110); `bin/mcp-run.sh` launches the server
- `agents/mikrotik.md` — the OpenCode subagent that keeps the native `mikromcp_*` tools
- opskit #314 — why the schemas are not always-on in any runtime
