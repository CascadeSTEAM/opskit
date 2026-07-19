---
rule: iac-required
description: All system-state operations — remote hosts AND the local workstation — MUST be Ansible playbooks in ansible/playbooks/
---

# IaC Mandatory Rule

Every system-state operation — DNS, packages, configs, network, credentials, monitoring,
deployments, backups, SSH config — MUST be an Ansible playbook in `ansible/playbooks/`.

**This includes the local workstation.** OS/app/configuration maintenance of the machine
you are on targets the `workstations` group (`ansible_connection: local`).

**Ansible is the codification target of the automation ladder for system-state work.**
When `bin/automation-ladder.py` offers to codify a repeated task and that task changes
the state of any system (remote or local), the script rung of the ladder IS an Ansible
playbook/role — plain shell/python scripts are reserved for repo/dev workflow (git,
tickets, docs, lifecycle). repetition → skill → **ansible playbook** → MCP tool.

**If you find yourself doing something manually a second time, stop — write the playbook
first** (and journal it: `python3 bin/automation-ladder.py log --task <slug>`).

**No exceptions except:** read-only probes (curl/ping/dig), active incident response (playbook
required same session), and initial Ansible bootstrap.

**Playbook standards:** idempotent, use `ansible-vault` for secrets, hosts in
`environments/<env>/ansible/inventory.yml`, clear name/purpose header.
