# Rule: Prefer Project Tools Over Ad-hoc Bash

## Core Principle

**Before writing a bash command, ask: does this project already have a tool for this?**

Use the project's own scripts, skills, and Ansible playbooks in preference to ad-hoc one-liners.
Ad-hoc bash is a last resort for truly one-off situations with no existing tool.

---

## Query Tools (read-only state inspection)

| What you want to know | Use this |
|----------------------|----------|
| Proposals awaiting approval | `python3 scripts/lifecycle-processor.py --status` |
| Active / in-progress plans | `python3 scripts/lifecycle-processor.py --status` |
| Pending lifecycle transitions | `python3 scripts/lifecycle-processor.py --dry-run` |
| Device/network inventory | `python3 scripts/scanner/scan.py --list` then read `inventory/datasets/<name>/` |
| Available datasets | `python3 scripts/scanner/scan.py --list` |

**Do NOT** use `grep -r "approved: false"`, `find proposals/ -name "*.md"`, or similar
ad-hoc frontmatter queries. The lifecycle-processor is the authoritative query interface.

---

## Infrastructure Operations

**Do NOT** write ad-hoc bash for repeatable infrastructure tasks. See `iac-required.md`.
All infra operations → Ansible playbooks in `ansible/playbooks/`.

---

## Skills First

If you are running inside OpenCode, prefer skills over raw bash:

| Task | Skill |
|------|-------|
| Lifecycle transitions, proposals, plans | `lifecycle` |
| Git commits, branch management | `git` |
| Credentials, security, firewall, VLAN | `security` |
| Backup / restore | `backup` |
| LXC, Proxmox, deployment | `infra` |
| SSH access, host connections | `ssh-access` |
| Zabbix monitoring | `zabbix` |
| Security audit tools | `tools` |

Load with: `opencode tool skill use <name>`

---

## Decision Tree

```
Need to query project state?
  → Use lifecycle-processor.py --status or --dry-run

Need to inspect inventory?
  → Read inventory/datasets/<name>/ YAML files directly
  → Or use scanner: python3 scripts/scanner/scan.py --list

Need to do an infrastructure operation?
  → Is there already a playbook in ansible/playbooks/?
      YES → Run it: ansible-playbook ansible/playbooks/<name>.yml
      NO  → Write the playbook first, then run it

Need something truly one-off (no script exists, no playbook needed)?
  → Ad-hoc bash is permitted — but document the command in the session note
  → If you run it twice, it was never one-off — write the playbook
```

---

## Rationale

- Keeps AI behaviour auditable and reproducible
- Prevents query logic drift (frontmatter schema changes break ad-hoc grep silently)
- Forces reuse of tested tooling rather than parallel invention
- Consistent with the IaC mandate already in `iac-required.md`
