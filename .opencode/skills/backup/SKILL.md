---
name: backup
description: Backup schedule, storage locations, and recovery procedure
mode: skill
triggers: backup,recovery,restore,snapshot,disaster
---

# backup

> Load this skill when discussing backup status, storage locations, restore procedures, or backup failures.

0. Track usage: `python3 bin/automation-ladder.py tick --skill backup` — if the output has `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill backup`.

## Schedule

| Frequency | Task |
|-----------|------|
| Daily | Router config export, Git repo push |
| Weekly | Proxmox VM/CT backups |
| Monthly | Vault export |
| Quarterly | Test restore from backup |
| Annually | Full disaster recovery drill |

## Recovery

1. Identify backup to restore; verify integrity before restore
2. Restore to test environment first when possible
3. Document restore procedure and any issues

## Key Rules

- Always verify backup after creation
- Alert on failure — wire it to the environment's monitoring/alerting stack
- Prune old backups — avoid disk full on the backup target

## Related

- `ansible/playbooks/zabbix-backup.yml` — codified backup play
- Storage locations, retention targets, and offsite config are env-specific:
  read them from `environments/<env>/` (never committed here)
