---
name: zabbix
description: Zabbix tiered monitoring design, Ansible components, and API troubleshooting
mode: skill
triggers: zabbix,monitoring,snmp,alert,tiered,grafana,discovery
---

# zabbix

> Load this skill when working with Zabbix monitoring, discovery rules, device
> templates, or alert configuration.

0. Track usage: `python3 bin/automation-ladder.py tick --skill zabbix` — if
   `"offer_upgrade": true`, offer codification per Development Principles;
   permanent "no" → `python3 bin/automation-ladder.py mute --skill zabbix`.

## Tiered Monitoring Design

| Tier | Hosts | Monitoring | Alerts |
|------|-------|-----------|--------|
| T1 — Infrastructure | Hypervisors, servers, network gear | Full agent or SNMP | High/Average/Warning → push + email |
| T2 — IoT/Appliance | Smart devices, appliances | ICMP or agent | Warning only (dashboard) |
| T3 — Ephemeral | Dynamic/temp hosts | ICMP, history only | None — tracked, not alerted |
| T4 — Unknown | Auto-discovered, unclassified | ICMP | None — auto-removed after 7 days unseen |

## Ansible Components

| Component | Path |
|-----------|------|
| Agent role | `ansible/roles/zabbix_agent/` |
| Server role | `ansible/roles/zabbix_server/` |
| Backup play | `ansible/playbooks/zabbix-backup.yml` |

Host lists and per-tier membership are environment data — read them from
`environments/<env>/`, never from this committed skill.

## Key API Rules (Zabbix 7.2)

Hard-won and non-obvious; each one is a silent failure if you get it wrong.

- **Auth**: `Authorization: Bearer <token>` header — not the legacy `auth`
  JSON field
- **Discovery actions**: `action.*` with `eventsource: 1` — NOT `daction.*`,
  which was removed in 7.2
- **Network map links**: `selementid1` / `selementid2` — NOT
  `selementid_from` / `selementid_to`
- **Dashboard widget fields**: `type`/`name`/`value` format; arrays use dot
  notation (`groupids.0`, `groupids.1`)

## Troubleshooting

| Problem | Check |
|---------|-------|
| Agent not reporting | `systemctl status zabbix-agent2`; verify `Server=` in config; check firewall port 10050 |
| SNMP timeout | `snmpwalk -v2c -c <community> <host>`; verify community string; port 161 open from server |
| Discovery noise | Adjust T4 auto-cleanup (7 days); promote a persistent device to a real tier |
| Dashboard not rendering | Verify `groupids` in widget fields match actual host group IDs |
