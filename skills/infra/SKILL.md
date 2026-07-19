---
name: infra
description: Infrastructure placement rules, node roles, and reliability standards across all cluster networks
mode: skill
triggers: lxc,proxmox,deploy,placement,commission,decommission,vm,container
---

# infra

> Load this skill when placing, deploying, or decommissioning any LXC, VM, or service.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill infra` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 scripts/automation-ladder.py mute --skill infra`.

## Placement Rules

- All services run in LXCs/VMs — **never directly on hypervisors**
- Static IPs required; assign in `inventory/datasets/<network>/ipam.yml` before deploying
- Ansible provisioning required — no manual installs
- Document in `inventory/datasets/` before deployment

## Node Roles

| Node | IP | Role | Notes |
|------|----|------|-------|
| frank | 10.99.0.13 | Proxmox host | GPU, AI compute |
| cluster-llm | 10.99.0.201 | LXC | Ollama hub (only hypervisor exception) |
| lab1–3 | 10.99.0.211–213 | Proxmox + Ollama | Distributed inference |
| lab4 | 10.99.0.214 | Proxmox + Ollama | Currently unreachable — verify before use |
| nuk1 | 10.99.0.215 | Proxmox + Ollama | Backup inference |

## Reliability (N+1)

- Critical services run on 2+ nodes
- Health checks every 60s; auto-failover for DNS, Monitoring, Ollama
- Technitium DNS at 10.99.0.4

## Key Rules

- `lifecycle_status`: `planned → active → deprecated → decommissioned` — update in device YAML
- Never set `lifecycle_status: decommissioned` without explicit human instruction
- Exporters (node_exporter, etc.) may run directly on hosts — the only exception to the LXC rule

## Related

- `inventory/datasets/` — canonical device source of truth
- `docs/SOPs/infra-topology.md` — full lifecycle SOP
- `ansible/playbooks/` — all provisioning playbooks
