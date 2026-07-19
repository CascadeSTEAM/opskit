# AGENTS.md — Agent Guidelines for opskit

## Behavioral Hard Rule — Read Before Every Response

**When the human says "stop" or calls out a bad pattern: STOP.** No more tool calls. No "one more check." Acknowledge in plain language and wait.

**Diagnostic order:** Logs → Connectivity test → Config inspection. Never config-first.

**Cycle detection:** After 2 failed attempts at the same approach, STOP and present all findings. Do not try a third variation. If you've made 3 tool calls without showing results to the human, you're cycling — tell them.

**Announce toolset before acting:** Before the first tool call on any task, state what tools you will use and why. Example: *"I'll use mikromcp_get_system_status to check the router, then mikromcp_create_backup before upgrading."* Wait for a go/no-go. This is not optional.

**Tool selection by domain (enforced by subagents — see below):**
- MikroTik/RouterOS → use `@mikrotik` subagent (relay-shell denied at runtime)
- Linux server ops → use `@linux` subagent (mikromcp tools denied at runtime)
- Default task → use `build` agent (full tool access, bash: ask)

If you are NOT in a domain-specific subagent and the task matches one, switch. Example: user asks about a router → invoke `@mikrotik` via Task tool.

## Core Rules
- **ALWAYS VERIFY** — never assume IPs, credentials, or roles are current.
- **Data-driven everything** — environment config lives in `environments/<env>/env.yml`. Never hardcode environment names, hostnames, or subnets. Discover them at runtime.
- **IaC mandatory** — every repeatable system-state operation → Ansible playbook. Local workstation maintenance too — target the `workstations` group (`ansible_connection: local`). See `.opencode/rules/iac-required.md`.
- **One-off tasks prohibited** — all work flows through the document lifecycle.
- **Multi-system repo** — never assume a specific host. Check connectivity before infra operations.
- **Hooks auto-setup** — at session start, verify `core.hooksPath` is `.githooks`. If not, run `bash bin/setup-hooks.sh` to ensure consistent commit enforcement across all clones.
- **Document as you go** — every change to infrastructure MUST be recorded in device YAMLs, docs, or vault in the same session. See `.opencode/rules/document-as-you-go.md`.
- **SSH aliases REQUIRED** — never connect by raw IP. Always read `~/.ssh/config` first and use the defined host alias.

## Environment Model

opskit is env-agnostic. Everything reads from `environments/<env>/env.yml`:

```
environments/
  example/              # committed — reference templates only
    env.yml
    ansible/
    datasets/devices/
  <your-env>/           # gitignored — your real data
    env.yml             # canonical env config (name, subnets, ticket prefix, ...)
    ansible/
      inventory.yml     # ansible host inventory
      group_vars/
      host_vars/
    datasets/devices/   # device YAML definitions
    playbooks/           # env-specific playbooks
```

**Dogfooding safety:** `environments/*/` (except `example/`) is gitignored. Your real network data never touches git.

## Tool Scripts (bin/)

All scripts are data-driven — they read from `environments/$ACTIVE_ENV/env.yml`.

| Script | Purpose |
|--------|---------|
| `bin/switch-env.sh <env>` | Set ACTIVE_ENV, probe connectivity |
| `bin/check-connectivity.sh [env]` | Probe all connectivity targets from env.yml |
| `bin/ap.sh <playbook>` | Run Ansible playbook with `--limit` scoped to ACTIVE_ENV |
| `bin/open-ticket.sh [subject]` | Manage helpdesk tickets (reads env.yml for prefix/endpoint) |
| `bin/scan.py` | Nmap discovery, enrich YAML device datasets |
| `bin/automation-ladder.py` | Track manual processes → escalate to scripts/playbooks |
| `bin/lifecycle-processor.py` | Manage lifecycle transitions |

## Subagents (invoke with @name)
- `@lifecycle` — lifecycle transitions, proposal→plan→completed
- `@incident` — incident, breach, outage, P1-P4 response
- `@skill-builder` — create/fix/audit OpenCode skills
- `@mikrotik` — RouterOS devices: switches, routers, WiFi APs, CAPsMAN (relay-shell denied, mikromcp only)
- `@linux` — Linux server administration: Ubuntu, Ansible, Docker, Proxmox (mikromcp denied)

Always use `@skill-builder` for new skills — enforces 4-field frontmatter and 60-line limit.

**Domain enforcement:** These agents have runtime-enforced tool permissions. `@mikrotik` has `relay-shell_*` denied at the OpenCode runtime level, and `@linux` has `mikromcp_*` denied.

## Skills (load with: opencode tool skill use <name>)
`lifecycle` | `git` | `security` | `backup` | `infra` | `check-connectivity` | `templates` | `tools` | `endsession`

Load the relevant skill before working in its domain.

## Development Principles

Set by the project owner; they apply to every session, not per-task.

1. **Never lose an idea.** An idea that surfaces in conversation and isn't acted
   on immediately gets captured before the session ends — as an `issues/` file
   (lifecycle entry point) or a helpdesk ticket, whichever fits.

2. **Escalate repetition into automation.** Manual work climbs a ladder —
   `bin/automation-ladder.py` measures each rung:
   - A process done by hand **2–3 times** → offer to codify it as a **skill**
   - A skill invoked **more than ~3 times** → offer to replace its manual steps
     with a codified tool. If the work changes system state, the tool IS an
     **Ansible playbook/role** in `ansible/`. Plain scripts are only for
     repo/dev workflow.
   - A playbook/script that earns heavy use → offer to expose it as a
     **MCP tool**.
   State lives in `.local/` (gitignored, shared across worktrees).

## Lifecycle Rules
`issues/` → `proposals/` → `proposals/approved/` → `plans/` → `plans/completed/` (→ `docs/`)

- `proposals/`: `approved: false`. Duplicate check required before creation.
- `proposals/approved/`: only humans set `approved: true`. Requires non-empty `assigned_to`.
- `plans/`: created from approved proposals. `status: in_progress` for active execution.
- `plans/completed/`: completed → generate docs; canceled → no docs.
- NEVER set `lifecycle_status: decommissioned` without explicit human instruction.

## Model Tiers
- **T1** (`claude-*`, `big-pickle`): full capabilities
- **T2** (`mistral-small3.2:24b`, `qwen2.5:14b`, `qwen3.5:27b`): full lifecycle + mandatory dry-run gate before transitions
- **T3** (`llama3.1:8b`, `qwen2.5:7b`, `deepseek-r1:14b`, `gemma3:12b`): draft and query only — no writes, no bash
- **T4** (`qwen2.5:1.5b`, `nomic-embed-text`): utility/embeddings only

For sessions requiring tool use, select a T1 or T2 model explicitly.

## Security
- OpenCode server bound to `127.0.0.1`, password via `OPENCODE_SERVER_PASSWORD`
- systemd units run with `NoNewPrivileges=true`
- One-off tasks bypassing `plans/` are rejected
- Credentials referenced by vault name only — never plaintext. See `.opencode/rules/no-plaintext-creds.md`.

## Session Artifacts
Both must be updated at session end — do not skip:
- **SESSION-LOG.md** — strategic entry: key decisions, architectural choices, open threads
- **`docs/session-notes/`** — operational log: commands run, errors encountered, undo instructions

## Helpdesk Ticket Tracking (Hard Rule)

**Every infra change must reference a helpdesk ticket. Pre-commit enforces this.**
The hook reads `ACTIVE_ENV` from `.env` and ticket prefix from `environments/<env>/env.yml`.

### Session start sequence (required before any infra change)

```bash
bash bin/switch-env.sh <env>               # sets ACTIVE_ENV, clears .current-ticket
bash bin/open-ticket.sh "what you're doing" # creates ticket → writes .current-ticket
```

### Commit format

```
<prefix>-<num>: <description>
```

**Exemptions:** read-only diagnostics with zero live changes; `.md`-only commits.

**Do not answer device/network/project questions from memory — the data changes.
Call the relevant tool first, then answer from its output.**
