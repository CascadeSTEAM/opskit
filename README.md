# OpsKit

**Infrastructure-as-code toolkit for managing network gear, servers, DNS, and
AI agents — all data-driven from a single environment config.**

OpsKit is a unified toolkit that replaces ad-hoc SSH sessions, scattered scripts,
and manual configs with a repeatable, auditable, and rebuildable infrastructure
management system. It manages MikroTik routers/switches, Proxmox clusters, DNS/DHCP,
and AI agents — all governed by a single `env.yml` per environment.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/CascadeSTEAM/opskit.git $HOME/Projects/opskit
cd $HOME/Projects/opskit

# 2. Run the interactive installer
bash install.sh

# 3. Pick an example environment and go
bash bin/switch-env.sh example
```

That gives you a working toolkit. For a fully capable workstation (MCP servers,
Ansible collections, vault access), see [docs/INSTALL.md](docs/INSTALL.md).

## What You Get

| Layer | Capability |
|-------|-----------|
| **CLI tools** | Device scanning, schema validation, ticket management |
| **Ansible** | Infrastructure-as-code — every system change is a playbook |
| **AI agents** | Domain-specialized subagents (RouterOS, Proxmox, Linux, DNS) |
| **Environments** | Isolated configs for each network/project you manage |

## Directory Structure

```
opskit/
├── bin/                  # CLI tools and automation scripts
├── ansible/              # Playbooks and roles (infrastructure-as-code)
│   ├── playbooks/        # Execution-level runbooks
│   └── roles/            # Reusable role definitions
├── environments/         # Per-environment configs (your real data)
│   ├── example/          # Fictional reference environment (committed)
│   └── <your-env>/       # Your actual devices and credentials
├── mcp/                  # AI agent tool servers (MCP protocol)
├── docs/                 # Guides: install, architecture, onboarding
├── schemas/              # JSON schemas for env.yml and device records
├── .opencode/            # AI agent skills, rules, and configuration
│   ├── skills/           # Domain knowledge (zabbix, mikrotik, etc.)
│   └── rules/            # Behavioral rules for agents
├── agents/               # Domain subagent definitions
├── tests/                # Test suite
└── plans/                # Work plans (issue → proposal → plan → done)
```

## Key Concepts

### Environments
Every network or project you manage is an **environment** — a directory under
`environments/` with a single `env.yml` that describes subnets, devices,
credentials, and ticket prefixes. The entire toolkit reads from this file;
nothing is hardcoded.

### Ansible-first
Every repeatable infrastructure change is an Ansible playbook. Manual ad-hoc
commands are temporary; the playbook is the durable record. Run playbooks with:

```bash
bash bin/ap.sh ansible/playbooks/my-playbook.yml
```

### AI Agents
OpsKit ships with domain-specialized AI subagents (`@mikrotik`, `@linux`,
`@technitium`, `@proxmox`) that enforce tool permissions — e.g. RouterOS
changes only go through the MikroTik MCP server, never direct SSH.

## Basic Operations

### Switch environments
```bash
bash bin/switch-env.sh <env>
```

### Check network reachability
```bash
bash bin/check-connectivity.sh
```

### Scan for devices on your subnets
```bash
bash bin/scan.py
```

### Create a helpdesk ticket
```bash
bash bin/open-ticket.sh "my change description"
```

### Check AI agent capabilities
```bash
opencode debug agent <name>    # e.g. @mikrotik, @linux
```

## For Contributors

```bash
# Install test dependencies
make deps

# Run the full test suite (CI runs this)
make test

# Lint shell scripts and Ansible
make lint

# Run publication guards (pre-commit hook)
bash bin/setup-hooks.sh
make guard
```

## Further Reading

- [docs/INSTALL.md](docs/INSTALL.md) — Full workstation installation guide
- [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) — How environment configs work
- [docs/DEV-GUIDE.md](docs/DEV-GUIDE.md) — How to add playbooks, agents, MCP servers
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System architecture overview
- [CONTRIBUTING.md](CONTRIBUTING.md) — Contribution guidelines
- [AGENTS.md](AGENTS.md) — Full agent behavioral rules (advanced)

## License

MIT — see [LICENSE](LICENSE).
