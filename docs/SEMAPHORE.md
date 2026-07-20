# Semaphore UI (optional)

Semaphore UI provides a web-based dashboard for running Ansible playbooks with
role-based access control, scheduling, and audit trails.

**Semaphore is optional.** Playbooks run fine from the CLI via `bin/ap.sh`.
Semaphore adds a GUI, scheduling, and multi-user support.

## When to use Semaphore

- Multiple operators need to run playbooks (without SSH access to the opskit host)
- You want a schedule (e.g., health check every hour, backup every night)
- You want audit trails of who ran which playbook and when
- You prefer clicking buttons over typing commands

## When to skip it

- Solo operator — `bin/ap.sh` is faster
- No web server available to host it
- You don't need scheduling or audit trails

## Setup

1. Deploy Semaphore (Docker is the simplest path):

```bash
docker run -d --name semaphore \
  -p 3000:3000 \
  -v /opt/semaphore:/etc/semaphore \
  semaphoreui/semaphore:latest
```

2. Configure Semaphore (web UI at `http://host:3000`):
   - Create a project matching your environment name
   - Add your SSH key in Key Store
   - Add your Ansible inventory (can point to `environments/<env>/ansible/inventory.yml`)

3. Set your env.yml:

```yaml
execution:
  type: semaphore
  semaphore_url: "http://host:3000/api"
  semaphore_project: "homelab"
```

4. Sync your playbook catalogue to Semaphore:

```bash
bin/semaphore-sync.py
```

This creates Semaphore task templates from your Ansible playbooks, including
ticket-reference survey prompts for infrastructure changes.

## How semaphore-sync.py works

- Reads the opskit Ansible catalogue (`ansible/playbooks/`)
- Creates or updates a Semaphore project matching your environment
- Creates an inventory in Semaphore pointing to `environments/<env>/ansible/inventory.yml`
- Creates task templates with the playbook path, environment variables, and
  a survey prompt for the ticket reference
- Idempotent — running it again updates, never duplicates

## MCP integration

`mcp/semaphore-mcp-adapter.py` provides an MCP server for AI agents to interact
with Semaphore — list templates, trigger tasks, check status. This is optional
and requires the Semaphore server to be reachable.

## CLI vs Semaphore

| Feature | CLI (`bin/ap.sh`) | Semaphore |
|---------|-------------------|-----------|
| Run playbooks | Yes | Yes |
| Scheduling | No (use cron) | Yes |
| RBAC | No (OS users) | Yes |
| Audit trail | Shell history | Built-in |
| AI agent access | Via `bash` tool | Via MCP adapter |
| Setup | Zero (included) | Docker + config |
