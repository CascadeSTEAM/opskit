---
status: open
created: "2026-07-19"
priority: high
tags: [bms, semaphore, ansible, deployment]
---

# Deploy Semaphore UI on BMS Network

Semaphore UI provides a web interface for running Ansible playbooks with RBAC,
scheduling, and audit trails. The BMS environment needs a Semaphore instance to
enable multi-operator playbook execution from the web UI.

**Target host:** `playbook` LXC (10.99.0.15, CT 131 on pve2) — currently stopped,
originally created as "Ansible playbook runner LXC."

**Scope:** Bring up the stopped playbook LXC, deploy Semaphore via the existing
`ansible/roles/semaphore` role, create a playbook, and configure it for BMS.
