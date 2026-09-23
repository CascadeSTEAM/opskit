---
name: proxmox-cli
description: "Reach the Proxmox VE MCP server from any agent runtime that does not hold its native tool schema — Claude Code and every OpenCode/Crush agent without direct proxmox_* access — through bin/mcp-call.py proxmox, the same vault-resolved launcher the native tools use. Use for: proxmox, pve, lxc, vm, container, virtual machine, proxmox cluster"
mode: skill
triggers: proxmox,pve,lxc,vm,container,virtual machine,proxmox cluster,qemu
---

# proxmox-cli

> Claude Code has no MCP servers configured at all, and no runtime other than
> the ones that carry `proxmox_*` natively can reach a Proxmox cluster
> directly. `bin/mcp-call.py proxmox` reaches the same vault-resolved server
> through a shell call instead — same credentials, same launcher
> (`bin/mcp-run.sh`) the native tools use.
>
> **Multi-environment**: this repo tracks several Proxmox clusters
> (`mcp/tenants-proxmox.local.json`). The server picks one via `PROXMOX_ENV`
> or `ACTIVE_ENV` (from `.env` / `opskit env`) — confirm the active
> environment matches the cluster you mean to touch before any call, e.g.
> `PROXMOX_ENV=<env> bin/mcp-call.py proxmox get_nodes`.

## Quick Reference

| Need | Command |
|---|---|
| Can the server serve right now? | `bin/mcp-call.py proxmox --probe` |
| Every tool with its schema | `bin/mcp-call.py proxmox --list` |
| Cluster/node health | `bin/mcp-call.py proxmox get_cluster_status` · `get_nodes` · `get_node_status --arg node=<node>` |
| List VMs / containers | `bin/mcp-call.py proxmox get_vms` · `get_containers` |
| Guest config / IPs | `bin/mcp-call.py proxmox get_vm_config --arg vmid=<id>` · `get_container_ip --arg vmid=<id>` |
| Storage / ISOs / templates | `bin/mcp-call.py proxmox get_storage` · `list_isos` · `list_templates` |
| Next free VMID | `bin/mcp-call.py proxmox get_next_vmid` |
| Power state | `bin/mcp-call.py proxmox start_vm --arg vmid=<id>` · `stop_vm` · `shutdown_vm` · `reset_vm` · `start_container` · `stop_container` · `restart_container` |
| Snapshots | `bin/mcp-call.py proxmox create_snapshot '{...}'` · `list_snapshots --arg vmid=<id>` · `rollback_snapshot '{...}'` · `delete_snapshot '{...}'` |
| Backups | `bin/mcp-call.py proxmox create_backup '{...}'` · `list_backups` · `restore_backup '{...}'` · `delete_backup '{...}'` |
| Create/delete guests | `bin/mcp-call.py proxmox create_vm '{...}'` · `create_container '{...}'` · `delete_vm --arg vmid=<id>` · `delete_container --arg vmid=<id>` |
| Long-running jobs (clone, restore, etc.) | `bin/mcp-call.py proxmox list_jobs` · `get_job --arg job_id=<id>` · `poll_job --arg job_id=<id>` · `cancel_job --arg job_id=<id>` · `retry_job --arg job_id=<id>` |
| Logs | `bin/mcp-call.py proxmox get_cluster_log` · `get_node_syslog --arg node=<node>` · `get_task_log --arg upid=<upid>` · `get_guest_firewall_log --arg vmid=<id>` · `get_node_firewall_log --arg node=<node>` |
| Guest commands (needs QEMU agent) | `bin/mcp-call.py proxmox execute_vm_command '{...}'` |

`--arg` coerces JSON scalars (numbers, `true`/`false`, `null`); bare words
stay strings. Use `--str k=v` when a value must stay a string. Multi-field
calls (create/update/restore) are easier as one JSON blob:
`bin/mcp-call.py proxmox create_container '{"node":"pve1","vmid":701,...}'`.

## Steps

1. Confirm the active environment/cluster (`opskit env`, `list_targets`)
   before any call — the wrong `PROXMOX_ENV` talks to the wrong cluster
   silently.
2. **Read before you write**: `get_vms`/`get_containers`/`get_vm_config`
   first, so a create/update/delete is against known current state.
3. Anything destructive (`delete_vm`, `delete_container`, `delete_backup`,
   `delete_snapshot`, `restore_backup`) is felt immediately with no undo
   beyond a fresh backup/snapshot — confirm intent explicitly before calling.
4. Prefer Ansible playbooks (`ansible/playbooks/`) for anything repeatable —
   this skill is for reads, diagnosis, and one-off/emergency changes that
   then get codified (IaC rule).
5. Report the exact guest/node/resource changed and its resulting state.

## Failure handling

- "vault is LOCKED" / no `BW_SESSION`: ask the operator to refresh it
  (`bwunlock` skill) — never run `bw unlock` yourself.
- `error: the server exited without responding` naming a missing node for
  the active environment: the wrong `PROXMOX_ENV` is set — check
  `mcp/tenants-proxmox.local.json` for which environments have a configured
  cluster.
- Failure output may quote server stderr containing credentials: read it,
  act on it, never paste it into an issue, PR, or public channel.

## Related

- `bin/mcp-call.py` — the one-shot MCP client (opskit #110); `bin/mcp-run.sh`
  launches the server
- `mcp/proxmox-mcp-server.py` — the server implementation
- `docs/proxmox-mcp-setup.md` — Proxmox MCP setup reference
- `routeros` skill — the same bridge pattern, first built for mikromcp
