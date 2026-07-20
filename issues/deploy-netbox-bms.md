---
status: open
created: "2026-07-19"
priority: high
tags: [bms, netbox, deployment]
---

# Deploy Netbox on BMS Network

Netbox is the source-of-truth IPAM/DCIM tool. BMS currently uses `git-yaml` as
source-of-truth type. Deploying Netbox opens the path to migrate to `type: netbox`.

**Target host:** New LXC on pve2 (to be created).

**Scope:** Provision a new LXC on pve2, deploy Netbox (Docker Compose recommended
per upstream), create an Ansible role and playbook. The existing `ansible/roles/netbox`
is empty — needs to be filled out.
