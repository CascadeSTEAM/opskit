---
name: zabbix
description: Zabbix tiered monitoring design, Ansible components, and troubleshooting for the AI cluster
mode: skill
triggers: zabbix,monitoring,snmp,alert,tiered,grafana,mikrotik,discovery
---

# zabbix

> Load this skill when working with Zabbix monitoring, discovery rules, MikroTik templates, or alert configuration.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill zabbix` — if `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `automation-ladder.py mute --skill zabbix`.

## Tiered Monitoring Design

| Tier | Hosts | Monitoring | Alerts |
|------|-------|-----------|--------|
| T1 — Infrastructure | Proxmox, servers, network | Full agent or SNMP | High/Average/Warning → push + email |
| T2 — IoT/Appliance | Smart devices, appliances | ICMP or agent | Warning only (dashboard) |
| T3 — Ephemeral | Dynamic/temp hosts | ICMP, history only | None — tracked, not alerted |
| T4 — Unknown | Auto-discovered, unclassified | ICMP | None — auto-removed after 7 days unseen |

## Ansible Components

| Component | Path | Purpose |
|-----------|------|---------|
| Role: zabbix-agent | `ansible/roles/zabbix-agent/` | Install agent (Debian/Alpine) |
| Role: zabbix-server | `ansible/roles/zabbix-server/` | Install server (Ubuntu) |
| `mikrotik-configure-rest-api.yml` | `ansible/playbooks/` | Configure RouterOS REST API (role was an empty scaffold, removed 2026-07-14) |
| `zabbix-configure-hosts.yml` | `ansible/playbooks/` | Host groups + auto-registration |
| `zabbix-configure-discovery.yml` | `ansible/playbooks/` | Network discovery rules |
| `zabbix-backup.yml` | `ansible/playbooks/` | PostgreSQL dump, 14-day retention |
| `zabbix-configure-mikrotik-http.yml` | `ansible/playbooks/` | Add MikroTik hosts with HTTP template |

## Key API Rules (Zabbix 7.2)

- **Auth**: `Authorization: Bearer <token>` header — not the legacy `auth` JSON field
- **Discovery actions**: `action.*` API with `eventsource: 1` — NOT `daction.*` (removed in 7.2)
- **Network map links**: `selementid1`/`selementid2` — NOT `selementid_from`/`selementid_to`
- **Dashboard widget fields**: `type/name/value` format; arrays use `groupids.0`, `groupids.1` dot notation

## Troubleshooting

| Problem | Check |
|---------|-------|
| Agent not reporting | `systemctl status zabbix-agent2`; verify `Server=` in config; check firewall port 10050 |
| SNMP timeout | `snmpwalk -v2c -c public <ip>`; verify community string; port 161 open from server |
| Discovery noise | Adjust T4 auto-cleanup (7 days); add persistent device to tier inventory |
| Dashboard not rendering | Verify `groupids` in widget fields match actual host group IDs |

## Do NOT

- Do NOT use `daction.*` for discovery actions in Zabbix 7.2+ (API removed)
- Do NOT use `selementid_from`/`selementid_to` in network map links (wrong field names)

## Related

- `docs/SOPs/zabbix-deploy-new-network.md` — full deployment procedure for a new network
- `docs/monitoring-infrastructure-yeticraft.md` — reference implementation
