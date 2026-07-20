---
name: backup
description: Backup schedule, storage locations, and recovery procedure for the AI cluster
mode: skill
triggers: backup,recovery,restore,snapshot,disaster
---

# backup

> Load this skill when discussing backup status, storage locations, restore procedures, or backup failures.

0. Track usage: `python3 scripts/automation-ladder.py tick --skill backup` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 scripts/automation-ladder.py mute --skill backup`.

## Schedule

| Frequency | Task |
|-----------|------|
| Daily | MikroTik config export, Git repo push |
| Weekly | Proxmox VM/CT backups |
| Monthly | VaultWarden export |
| Quarterly | Test restore from backup |
| Annually | Full disaster recovery drill |

## Storage Locations

| Location | Path / Repo | Contents |
|----------|------------|---------|
| frank (gemini) | `/home/gemini/backups/` | Proxmox VM/CT backups |
| GitHub | this repo's remote (e.g., `<org>/opskit`) | IaC repo |
| Offsite | TBD | Cloud storage (not yet configured) |

## Recovery

1. Identify backup to restore; verify integrity before restore
2. Restore to test environment first when possible
3. Document restore procedure and any issues in `docs/backup-test-log.md`

## Key Rules

- Always verify backup after creation
- Alert on failure via Grafana alert rule
- Prune old backups — avoid disk full on frank

## Related

- `ansible/playbooks/zabbix-backup.yml` — PostgreSQL Zabbix dump + 14-day retention
