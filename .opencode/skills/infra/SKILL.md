---
name: infra
description: Infrastructure placement rules, node roles, and reliability standards
mode: skill
triggers: lxc,proxmox,deploy,placement,commission,decommission,vm,container
---

# infra

> Load this skill when placing, deploying, or decommissioning any LXC, VM, or service.

0. Track usage: `python3 bin/automation-ladder.py tick --skill infra` — if the output has `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill infra`.

## Placement Rules

- All services run in LXCs/VMs — **never directly on hypervisors**
- Static IPs required; assign in IPAM before deploying
- Ansible provisioning required — no manual installs
- Document in device datasets before deployment

## Reliability (N+1)

- Critical services run on 2+ nodes
- Health checks every 60s
- Auto-failover for DNS, monitoring, and core services

## Key Rules

- `lifecycle_status`: `planned → active → deprecated → decommissioned` — update in device YAML
- Never set `lifecycle_status: decommissioned` without explicit human instruction
- Exporters (node_exporter, etc.) may run directly on hosts — the only exception to the LXC rule

## Related

- `environments/<env>/datasets/devices/` — canonical device source of truth
- `ansible/playbooks/` — all provisioning playbooks
