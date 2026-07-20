# Developer guide

How to extend opskit with new roles, playbooks, MCP servers, scanner sources,
and AI skills.

## Adding an Ansible role

Directory layout:
```
ansible/roles/<name>/
  tasks/main.yml
  templates/
  defaults/main.yml
  meta/main.yml
```

Rules:
- Credentials via `{{ lookup('env', 'VAR_NAME') }}` — never plaintext
- Declare supported OS families in `meta/main.yml`
- Use `ansible_os_family == 'Debian'` guards for apt-specific tasks
- Test with `bin/ap.sh <playbook> --check`

## Adding a playbook

Playbooks live in `ansible/playbooks/`. Template:

```yaml
---
# ansible/playbooks/my-playbook.yml
# Purpose: one-line description
# Hosts: proxmox_nodes
# Requires: ansible_user=root

- name: My Playbook
  hosts: "{{ target_group | default('all') }}"
  become: true
  vars:
    my_var: "{{ lookup('env', 'MY_VAR') }}"
  tasks:
    - name: do something
      ...
```

Use `bin/ap.sh` to run with environment isolation:
```bash
bin/ap.sh ansible/playbooks/my-playbook.yml
```

## Adding a scanner source

Scanner sources feed the `DeviceRegistry`. Create a module in `bin/scanner_lib/`:

```python
# bin/scanner_lib/source_proxmox.py
"""Pull VM/CT inventory from Proxmox API."""

def gather(proxmox_host: str, api_token: str) -> list[dict]:
    """Return list of device records."""
    records = []
    # ... API calls ...
    for vm in vms:
        records.append({
            'mac': vm['mac'],
            'ip': vm['ip'],
            'hostname': vm['name'],
            'type': vm['type'],   # lxc or qemu
            'source': 'proxmox',
        })
    return records
```

Sources are consumed by `device_registry.py`:
```python
from bin.device_registry import DeviceRegistry
reg = DeviceRegistry(router_hostname='my-router')
for record in source_proxmox.gather(...):
    reg.register(record, source='proxmox')
```

Source priority is automatic — values from higher-priority sources win:
```
manual=5 > proxmox=4 > technitium=3 > lldp=2 > bridge=1 > nmap=0
```

## Adding an MCP server

MCP servers expose opskit functionality to AI agents. Create `mcp/<name>-mcp-server.py`:

```python
#!/usr/bin/env python3
"""My Service MCP server — provides tool_name, other_tool."""
# Use the MCP SDK pattern from existing servers:
# mcp/erpnext-mcp-server.py
# mcp/technitium-mcp-server.py
# mcp/semaphore-mcp-adapter.py
```

Register in `opencode.json` to make it available to OpenCode:
```json
{
  "mcp": {
    "my-service": {
      "command": "python3",
      "args": ["mcp/my-service-mcp-server.py"]
    }
  }
}
```

## Adding a CLI subcommand

Extend `bin/opskit` — the CLI uses `argparse` subcommands:

```python
# in bin/opskit — add to main():

pc = sub.add_parser('my-command', help='what it does')
pc.add_argument('--flag', action='store_true')
pc.add_argument('target', nargs='?')

# Add to the dispatch:

if args.command == 'my-command':
    cmd_my_command(args)
```

## Directory conventions

| Directory | What belongs | What doesn't |
|-----------|-------------|--------------|
| `bin/` | CLI tools, scanner, registry | Playbooks, roles |
| `ansible/roles/` | Reusable Ansible roles | Site-specific config |
| `ansible/playbooks/` | Generic playbooks | Env-specific overrides (→ `environments/<env>/playbooks/`) |
| `mcp/` | MCP server scripts | MCP config (→ `opencode.json`) |
| `schemas/` | JSON Schema + contracts | Data (→ `environments/`) |
| `environments/example/` | Reference env (committed) | Real data (gitignored) |
| `.opencode/rules/` | AI behavioral rules | Project code |
| `.opencode/skills/` | AI domain knowledge | Project code |
| `docs/` | Architecture, guides | Lifecycle docs (→ `plans/`, `proposals/`) |

## Testing

```bash
# Schema validation
pytest tests/test_schemas.py -v

# Scanner library
pytest tests/scanner/ -v

# Adding new tests
# tests/scanner/test_<module>.py
```

Test fixtures:
- `tests/fixtures/` — nmap XML, example device YAMLs
- `environments/example/` — fictional reference environment for integration tests

## CI

CI runs on every push and PR (`main`):
- **lint** — shellcheck on `bin/` + ansible-lint (informational)
- **secret-scan** — grep for plaintext credentials
- **test** — full pytest suite
- **schema-check** — JSON Schema validation
- **e2e-pipeline** — end-to-end: switch-env → open-ticket → scan dry-run → isolation check

Non-blocking during migration: ansible-lint uses `continue-on-error`.
