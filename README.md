# opskit

Generic sysadmin toolkit — Ansible catalogue, CMDB pipeline, MCP servers, and
documentation framework for running heterogeneous network environments.

**opskit is glue, conventions, and a curated catalogue.** Heavy lifting is by
mature FOSS: [Ansible](https://ansible.com),
[Semaphore UI](https://semaphoreui.com) (optional),
[NetBox](https://netbox.dev), [Zabbix](https://zabbix.com),
[Vaultwarden](https://github.com/dani-garcia/vaultwarden), and
[DocWright](https://github.com/growlf/docwright).

## Quick start

```bash
git clone https://github.com/CascadeSTEAM/opskit
cd opskit
bash install.sh              # symlink to PATH, install completions, check deps
opskit check                 # verify everything
opskit setup                 # install pip deps + git hooks
opskit init homelab --subnets 192.168.1.0/24
opskit env homelab
opskit scan                  # nmap → YAML → enrich → resolve topology
opskit status                # inventory summary
```

## Commands

| Command | Purpose |
|---------|---------|
| `opskit check` | Verify dependencies (python, nmap, ansible, pip packages, hooks) |
| `opskit setup` | Install pip packages + configure git hooks |
| `opskit init <name>` | Scaffold a new environment in `environments/<name>/` |
| `opskit env [<name>]` | Show or switch active environment |
| `opskit scan` | Full pipeline: discover → parse → write → enrich → resolve uplinks |
| `opskit status` | Inventory summary by device role/type |
| `opskit setup-completion [bash|zsh]` | Install tab completion |

## Scan pipeline

```
Phase 1 — Nmap discovery (ARP sweep on subnets from env.yml)
Phase 2 — Write YAML device files to datasets/devices/
Phase 3 — Enrich: dedup by MAC, parent-child, infrastructure links
Phase 4 — Resolve uplinks via router bridge/LLDP, validate chains
```

```bash
opskit scan --dry-run          # preview, no network access
opskit scan --discover-only    # nmap discovery only
opskit scan --enrich-only      # re-run enrichment on existing data
opskit scan --uplinks-only     # only resolve topology
opskit scan --skip-uplinks     # skip topology (if no router access)
opskit scan --timeout 600      # override auto-timeout
```

## Project structure

```
opskit/
  bin/opskit               CLI entry point (symlinked to ~/.local/bin)
  bin/scan.py              Standalone scanner (called by CI)
  bin/scanner_lib/         Core scanning library (nmap, parser, writer, enricher)
  bin/device_registry.py   MAC-keyed identity resolution + uplink validation
  bin/*.sh                 Shell tools (switch-env, ap, check-connectivity, open-ticket)
  ansible/roles/           13 Ansible roles (zabbix, frappe, caddy, litellm, olla, ...)
  ansible/playbooks/       13 Ansible playbooks (health checks, DNS, firewall, ...)
  schemas/                 JSON Schema for env.yml and device.yml
  mcp/                     3 MCP servers (ERPNext, Technitium, Semaphore)
  environments/example/    Reference environment (committed)
  environments/<env>/      Your environments (gitignored)
    env.yml                Environment config (subnets, credentials, execution)
    ansible/inventory.yml  Ansible host inventory
    datasets/devices/      Device YAML definitions
    playbooks/             Environment-specific playbooks
  .opencode/               OpenCode AI integration (rules, skills, agents)
  agents/                  Subagent definitions (linux, mikrotik, lifecycle, ...)
```

## Data model

Every environment is a self-contained directory tree. Nothing is hardcoded.

**`environments/<env>/env.yml`** declares:
- **name, display_name** — identity
- **subnets** — named CIDR blocks (`mgmt: 10.0.0.0/24, servers: 10.0.1.0/24, ...`)
- **connectivity.probes** — reachability checks (host + port)
- **ticket** — helpdesk integration (prefix, endpoint, tenant)
- **vault** — secrets backend (vaultwarden, openbao, none)
- **source_of_truth** — NetBox or git-YAML canonical data
- **execution** — CLI or Semaphore UI
- **topology** — router hostname + SSH alias for bridge/LLDP resolution

**`environments/<env>/datasets/devices/*.yml`** — one file per device:
```yaml
device:
  name: my-router
  hostname: my-router.local
  mac_address: AA:BB:CC:DD:EE:FF
  ip_address: 10.0.0.1
  role: router
  status: active
  maturity: 3
  networking:
    interfaces: [...]
  dependencies:
    depends_on: [switch-01]
  monitoring:
    reachable: true
  metadata:
    created: "2026-01-01"
    source: nmap
```

See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) for the full env.yml contract.

## Semaphore (optional)

Semaphore UI provides a web interface for running Ansible playbooks, with RBAC,
scheduling, and audit trails. It is **completely optional** — `bin/ap.sh` runs
playbooks from the CLI.

To enable Semaphore:
1. Set `execution.type: semaphore` in `environments/<env>/env.yml`
2. Set `execution.semaphore_url` and `execution.semaphore_project`
3. Run `bin/semaphore-sync.py` to publish your playbook catalogue

See [docs/SEMAPHORE.md](docs/SEMAPHORE.md) for setup instructions.

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) and
[docs/DEV-GUIDE.md](docs/DEV-GUIDE.md) for architecture, conventions, and how
to add new roles, playbooks, MCP servers, or scanner sources.

## License

MIT — see [LICENSE](LICENSE).
