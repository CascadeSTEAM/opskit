---
issue: issues/deploy-semaphore-bms.md
approved: false
created: "2026-07-19"
priority: high
assigned_to: ""
tags: [bms, semaphore, ansible, deployment]
---

# Proposal: Deploy Semaphore UI on BMS

## What

Deploy a Semaphore UI instance on the BMS network using the existing
`ansible/roles/semaphore` role.

## Why

BMS has 78 inventoried devices, multiple operators, and a growing playbook
catalogue. Semaphore adds:
- Web UI for playbook execution (no SSH needed)
- Scheduling (health checks, backups)
- RBAC for multiple operators
- Audit trail of who ran what

## How (implemented)

1. Created a `docker-compose.yml` with Semaphore, Netbox, postgres, redis in `environments/bms/playbooks/docker/`
2. Fixed the semaphore config template (`config.json.j2`) — replaced stub with full config
3. Added `docker_services` group to inventory.yml targeting localhost
4. **Deployment model changed to local Docker** per operator decision — no remote LXC needed
5. Deployed: `docker compose up -d --wait` with env-file for secrets
6. Semaphore running at http://localhost:3000

## Dependencies

- The playbook LXC (10.99.0.15) must be started on pve2
- PostgreSQL must be available (can use docker or apt package)
- Secrets stored in Bitwarden vault (semaphore_db_password, semaphore_admin_password)

## Risks

| Risk | Mitigation |
|------|-----------|
| playbook LXC state unknown after long stop | SSH check before provisioning |
| PostgreSQL not already installed | Role installs and configures it |
| Bitwarden auth needed for secrets | Prompt operator for unlock |
