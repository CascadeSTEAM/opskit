# Session Note — 2026-07-19

## Commands Run

```bash
# Connectivity check
bash bin/switch-env.sh bms

# Docker stack deployment
docker compose -f environments/bms/playbooks/docker/docker-compose.yml \
  --env-file environments/bms/playbooks/docker/.env up -d --wait
docker compose ... down -v   # to recreate with DB init fix
docker compose ... up -d --wait  # final bring-up

# Verification
curl http://localhost:3000   # Semaphore — HTTP 200
curl http://localhost:8081   # Netbox — HTTP 302 → /login/ 200

# Git
git add ...
git commit -m "BMS-0106: feat: deploy Semaphore UI + Netbox via Docker Compose"
git push

# GitHub issues
gh issue create --title "..." --body "..." --label bug  # 7 issues created
```

## Errors Encountered

1. **open-ticket.sh NameError** — HELPDESK_TENANT undefined in Python heredoc (BMS-0106 commit, issue #6)
2. **Port 8080 conflict** — quartz-preview already bound; moved Netbox to 8081 (issue #1)
3. **Netbox DB missing** — postgres image doesn't create "netbox" DB; added init script (issue #5)
4. **Pre-commit hook** — required BMS-XXXX ticket format; used BMS-0106

## Undo Instructions

```bash
# Stop and remove the Docker stack (preserves volumes)
docker compose -f environments/bms/playbooks/docker/docker-compose.yml \
  --env-file environments/bms/playbooks/docker/.env down

# To also delete all data (postgres, semaphore config, netbox media):
docker compose -f environments/bms/playbooks/docker/docker-compose.yml \
  --env-file environments/bms/playbooks/docker/.env down -v

# Revert git commit (if needed):
git revert 232a20a
```
