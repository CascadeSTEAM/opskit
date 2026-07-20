# Contributing

opskit is MIT-licensed and accepts contributions. This document covers the
workflow, conventions, and standards.

## Getting started

```bash
git clone https://github.com/CascadeSTEAM/opskit
cd opskit
bash install.sh
opskit setup
opskit check
pytest tests/ -v
```

## Project conventions

1. **Data-driven everything** — no hardcoded hostnames, subnets, or env names.
   Everything reads from `environments/<env>/env.yml`.

2. **Environments are gitignored** — `environments/*/` except `example/` is
   in `.gitignore`. Real network data never touches git.

3. **IaC mandatory** — all system-state operations are Ansible playbooks.
   See `.opencode/rules/iac-required.md`.

4. **No plaintext credentials** — vault references only. Pre-commit hook
   enforces this.

5. **Commit format** — conventional commits with ticket prefix (where applicable):
   ```
   feat: add foo feature
   fix: correct bar behavior
   docs: update contributing guide
   ```

6. **Atomic commits** — one logical change per commit.

## Adding a new Ansible role

1. Create `ansible/roles/<name>/` with `tasks/main.yml`
2. Use `{{ lookup('env', 'VAR_NAME') }}` for credentials (never hardcode)
3. Add to the Semaphore sync whitelist in `bin/semaphore-sync.py` if it should
   appear in the UI

## Adding a new playbook

1. Create `ansible/playbooks/<name>.yml`
2. Use host groups that exist in the inventory template
3. Test with `bin/ap.sh ansible/playbooks/<name>.yml --syntax-check`

## Adding a new scanner source

The scanner pipeline is modular. To add a new data source (e.g., Proxmox API,
Technitium DHCP, NetBox export):

1. Create a source module in `bin/scanner_lib/` (e.g., `source_proxmox.py`)
2. Export a function that returns a list of host dicts with at minimum:
   `{mac, ip, hostname, source}`
3. Register hosts into `device_registry.py` with the source name:
   `reg.register(record, source='proxmox')`
4. The registry handles priority merging automatically

## Adding an MCP server

1. Create `mcp/<name>-mcp-server.py` using the MCP SDK
2. Add to `opencode.json` if it should be available to AI agents
3. Document the tools in the file's docstring

## Testing

```bash
pytest tests/ -v                  # all tests
pytest tests/test_schemas.py -v   # schema validation
pytest tests/scanner/ -v          # scanner library tests
```

Tests use:
- `environments/example/` — fictional reference environment
- `tests/fixtures/` — nmap XML fixtures for offline scan testing

## Submitting changes

1. Fork the repository
2. Create a feature branch: `feat/my-feature`
3. Make changes, run tests
4. Open a pull request against `main`

## AI agent integration

opskit ships with OpenCode integration in `.opencode/`:
- `rules/` — 9 behavioral rules for AI agents
- `skills/` — 9 domain-specific skills
- `agents/` — 5 subagent definitions (linux, mikrotik, lifecycle, incident, skill-builder)
- `AGENTS.md` — entry point for all AI coding agents

To add a new skill, use `@skill-builder` or create
`.opencode/skills/<name>/SKILL.md` with the 4-field frontmatter:
```yaml
---
name: my-skill
description: what it does
mode: skill
triggers: keyword1,keyword2
---
```

## Release process

- `main` is the development branch
- Tags are created for releases
- CI runs on every push and PR
