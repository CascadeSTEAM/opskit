# Global Memory — opskit Routing Instructions

## Infrastructure Work

All infrastructure work must use opskit tools. Never hardcode device names,
IP addresses, or credentials. Discover them at runtime through the
sanctioned tool paths.

## MCP Server Routing

When an MCP tool namespace is needed, use `bin/mcp-run.sh` to launch the
server. The server resolves secrets from the vault automatically.

| Namespace | Server | Launch |
|-----------|--------|--------|
| mikromcp | RouterOS devices | `bin/mcp-run.sh mikromcp` |
| erpnext | ERPNext helpdesk | `bin/mcp-run.sh erpnext` |
| technitium | DNS/DHCP | `bin/mcp-run.sh technitium` |
| proxmox | Proxmox VMs | `bin/mcp-run.sh proxmox` |
| bitwarden | Vault | `bin/mcp-run.sh bitwarden` |

## Agent Permissions

Domain-specific subagents have runtime-enforced tool permissions. RouterOS
devices can only be reached through the mikromcp namespace. Linux server
administration uses the @linux subagent. Direct SSH to RouterOS gear is
denied at runtime.

## Skills

Load skills before using them. The opskit skill tree is in `.opencode/skills/`.
Skills are loaded with: `opencode tool skill use <name>`

## Environment Selection

Before any infra work, set the active environment:
```bash
bash bin/switch-env.sh <env>
```

## Ticket Tracking

Every infra change must reference a helpdesk ticket. Run:
```bash
bash bin/open-ticket.sh "what you're doing"
```

## Git Workflow

Never commit infrastructure state to git. Real network data lives in
`environments/<env>/` (gitignored). Committed agents/skills/rules use
documentation-range IPs only.

## Vault Session

Before starting the agent runtime, export a vault session:
```bash
export BW_SESSION=$(bw unlock --raw)
```

Or use the session file:
```bash
mkdir -p ~/.cache/opskit
(umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)
```

## SSH Configuration

Never connect by raw IP. Always read `~/.ssh/config` first and use the
defined host alias. Connecting by raw IP is prohibited.

## SCP/RSYNC

When transferring files, use SSH aliases defined in `~/.ssh/config`.
Never use raw IPs for file transfers.

## Ansible

All repeatable system/deployment state operations are Ansible playbooks.
Use `bin/ap.sh` to run playbooks scoped to the active environment.

## MCP Server Configuration

Each MCP server is launched through `bin/mcp-run.sh`. The server resolves
secrets from the vault automatically. No manual vault configuration is
needed.

## Vault Map

The vault map is in `mcp/vault-map.local.json`. This file maps environment
variables to vault item/field references. Copy `mcp/vault-map.example.json`
and fill it in with your vault credentials.

## Client Tokens

Client tokens are in `.client-tokens`. This file is gitignored. Never
publish client-identifying data in git.

## Environment Repositories

Environment repositories are gitignored. Real environment data lives in
`environments/<env>/` (gitignored). Environment directories are single-branch
repos — pull/push refuse from anything but the default branch.

## Backup

Environment backups are in `environments/<env>/backups/`. Restore from
backup using `bin/env-sync.sh restore-remotes`.

## Session Artifacts

Session artifacts are routed per `docs/client-data-policy.md`:
- Public repo work → `docs/session-notes/` + a SESSION-LOG entry
- Live infrastructure work → `<env>/session-notes/`

## Definition of Done

Work isn't done until it's triaged, tested, documented, and stub-free.
Machine-enforced by `bin/definition-of-done-guard.py` in pre-commit + CI.

## Pre-commit Guards

Pre-commit guards enforce:
- No secrets in committed files
- No RFC1918 addresses in tracked files
- No stub markers in new skills
- New skills registered in AGENTS.md
- No client-identifying data in commit messages

## CI Pipeline

CI runs the full test suite (`make test`), lint (`make lint`), and
publication guards (`make guard`). All checks must pass before merging.

## GitHub Workflow

Never commit infrastructure state to git. Use worktrees for issue work.
Reference issues with `Closes #<n>` so merging closes them.

## Release Process

Version bumps are PR-based. Create a PR that closes the version issue.
The PR title should be `release: <version>`. The PR body should describe
the changes.

## Documentation

Documentation is in `docs/`. New documentation should follow the existing
format. Use the `templates/` directory for new document templates.

## Troubleshooting

If an MCP server fails to start, check:
1. The server path is correct
2. The vault session is available
3. The environment variables are set
4. The server dependencies are installed

If a playbook fails, check:
1. The inventory is correct
2. The environment is set
3. The ticket is active
4. The vault session is available

If tests fail, check:
1. The test suite is installed
2. The environment is set
3. The vault session is available
4. The git hooks are active

## Templates

Templates for `opencode.json` and `global-memory.md` are in `templates/`.
Copy them to configure the operator's environment. The templates are
redacted — no real paths or credentials. Fill in the parameterized
fields before use.

