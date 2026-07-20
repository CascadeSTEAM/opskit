---
issue: issues/deploy-netbox-bms.md
approved: false
created: "2026-07-19"
priority: high
assigned_to: ""
tags: [bms, netbox, deployment]
---

# Proposal: Deploy Netbox on BMS

## What

Deploy a Netbox instance on the BMS network with a new Ansible role and playbook.

## Why

BMS currently uses `source_of_truth.type: git-yaml`. Netbox provides:
- Centralized IPAM with API (replaces manual YAML editing)
- DCIM for tracking racks, devices, connections
- Web UI for browsing the network topology
- API that `bin/scan.py` can write to (replacing git-yaml writes)

## How (implemented)

1. Filled out the empty `ansible/roles/netbox/` (tasks, defaults, handlers)
2. **Deployment model changed to local Docker** per operator decision — no remote LXC needed
3. Single `docker-compose.yml` handles both Semaphore + Netbox with shared postgres/redis
4. Created `deploy-management-stack.yml` playbook in `environments/bms/playbooks/`
5. Added `docker_services` group to inventory.yml targeting localhost
6. Created device YAMLs for bms-docker-host, bms-semaphore, bms-netbox
7. Netbox running at http://localhost:8081 (port 8080 was occupied by quartz-preview)

## Dependencies

- A new LXC must be provisioned on pve2 (not done here — done on the Proxmox host)
- Network IP assigned from BMS subnet (10.99.0.0/16)
- DNS entry for netbox.bms.local

## Risks

| Risk | Mitigation |
|------|-----------|
| Netbox is a heavy Python/Django app | Docker Compose simplifies deployment |
| New LXC needed (not pre-existing) | Document provisioning steps |
| pve2 already hosts 23 LXCs | 125GB RAM available — fine |
| No netbox role content yet | Build from upstream docker-compose template |
