# SESSION-LOG

## 2026-07-19 — CLIENT1 Semaphore + Netbox Docker Deployment

**Key decisions:**
- Deployed Semaphore UI and Netbox as Docker containers on the local opskit workstation (not remote LXCs), per operator preference to "target the docker container like a normal machine"
- Shared PostgreSQL instance between both services to reduce resource footprint
- Netbox placed on port 8081 (8080 occupied by quartz-preview)
- Pinned Semaphore image to v2.10.18 (latest tag unreliable)

**Architectural choices:**
- Docker bridge network `client1-mgmt` (172.20.0.0/24) for service isolation
- Secrets stored in `environments/client1/playbooks/docker/.env` (gitignored, chmod 600)
- Ansible playbook (`deploy-management-stack.yml`) wraps docker compose with health checks
- Both roles (`netbox`, `semaphore`) updated for Docker-based deployment

**Open threads:**
- [ ] pve3 device YAML missing (#2) — needs `opskit scan`
- [ ] Duplicate client1/CLIENT1/ directories (#4) — needs sync and cleanup
- [ ] open-ticket.sh HELPDESK_TENANT fix (#6)
- [ ] Connect `bin/semaphore-sync.py` to the running Semaphore instance
- [ ] Configure Netbox as CLIENT1 source_of_truth (switch env.yml from git-yaml to netbox)
- [ ] Store generated secrets in Bitwarden vault (collection: client1) instead of local .env
- [ ] Add Caddy reverse proxy entries for public access to Semaphore and Netbox
- [ ] Lifecycle: transition proposals → approved → plans → completed

**Commit:** 232a20a (TKT-0106)
**GitHub issues:** #1-#7
