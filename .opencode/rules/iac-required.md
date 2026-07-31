---
rule: iac-required
description: All system/deployment-state operations — remote hosts AND the local workstation — MUST be Ansible playbooks in ansible/playbooks/. Application-record state inside a hosted app is out of scope; see the Scope section below.
---

# IaC Mandatory Rule

Every system/deployment-state operation — DNS, packages, configs, network, credentials,
monitoring, deployments, backups, SSH config — MUST be an Ansible playbook in
`ansible/playbooks/`.

**This includes the local workstation.** OS/app/configuration maintenance of the machine
you are on targets the `workstations` group (`ansible_connection: local`).

**Ansible is the codification target of the automation ladder for system/deployment-state
work.** When `bin/automation-ladder.py` offers to codify a repeated task and that task
changes the *system/deployment* state of any host (remote or local), the script rung of
the ladder IS an Ansible playbook/role — plain shell/python scripts are reserved for
repo/dev workflow (git, tickets, docs, lifecycle). repetition → skill →
**ansible playbook** → MCP tool (wrapper).

## Scope: system/deployment state only, not application records

This rule governs **system/deployment state** — provisioning, packages, services, config
files, baselines, reset procedures. It does **not** govern **application record state** —
API-driven CRUD, queries, or relationships inside a hosted app (example: creating or
updating an ERPNext HD Ticket via `mcp/erpnext-mcp-server.py`'s `erpnext_create_ticket`).
That work is interactive and data-returning rather than convergence-shaped, so Ansible
models it badly. For application record state, the codification target of the automation
ladder is an **MCP tool** directly (or a codified CLI where no agent surface is needed) —
not a playbook, and not a hand-rolled one-off script. See AGENTS.md Development
Principles #2.

**If you find yourself doing something manually a second time, stop — write the playbook
first** (and journal it: `python3 bin/automation-ladder.py log --task <slug>`).

**No exceptions except:** read-only probes (curl/ping/dig), active incident response (playbook
required same session), and initial Ansible bootstrap.

**Playbook standards:** idempotent, use `ansible-vault` for secrets, hosts in
`environments/<env>/ansible/inventory.yml`, clear name/purpose header.
