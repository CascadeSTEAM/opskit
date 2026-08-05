# AGENTS.md — Agent Guidelines for opskit

## Behavioral Hard Rule — Read Before Every Response

**When the human says "stop" or calls out a bad pattern: STOP.** No more tool calls. No "one more check." Acknowledge in plain language and wait.

**Diagnostic order:** Logs → Connectivity test → Config inspection. Never config-first.

**Cycle detection:** After 2 failed attempts at the same approach, STOP and present all findings. Do not try a third variation. If you've made 3 tool calls without showing results to the human, you're cycling — tell them.

**Announce toolset before acting:** Before the first tool call on any task, state what tools you will use and why. Example: *"I'll use mikromcp_get_system_status to check the router, then mikromcp_create_backup before upgrading."* Wait for a go/no-go. This is not optional.

**Tool selection by domain (enforced by subagents — see below):**
- MikroTik/RouterOS → use `@mikrotik` subagent (relay-shell denied at runtime).
  This says which tool an *agent* reaches for; it does not exempt RouterOS from
  the IaC rule — device state still belongs in a playbook so it can be rebuilt.
- Linux server ops → use `@linux` subagent (mikromcp tools denied at runtime)
- Security audit / SOC2 / CVE / hardening → use `@security-auditor` subagent (bash gated; reads the mounted opencode-auditor member)
- Default task → use `build` agent (full tool access, bash: ask)

If you are NOT in a domain-specific subagent and the task matches one, switch. Example: user asks about a router → invoke `@mikrotik` via Task tool.

## Core Rules
- **ALWAYS VERIFY** — never assume IPs, credentials, or roles are current.
- **Data-driven everything** — environment config lives in `environments/<env>/env.yml`. Never hardcode environment names, hostnames, or subnets. Discover them at runtime.
- **IaC mandatory — Ansible must be able to rebuild the whole infrastructure for a specific environment from
  zero.** That is the objective: emergency restoration, standing up a dev/test
  environment, onboarding a new device — while day-to-day changes stay fast. Every
  repeatable *system/deployment*-state operation (provisioning, packages, services,
  config files, baselines, reset procedures) → Ansible playbook. Local workstation
  maintenance too — target the `workstations` group (`ansible_connection: local`).
  *Application-record* state — API-driven CRUD/queries/relationships inside a
  hosted app — is out of scope; see Development Principles #2.
  **A domain having an MCP tool does NOT replace its playbook** — the playbook is
  the rebuild path, the MCP tool is for diagnosis and ad-hoc change, and an
  interactive change must be reflected back into the playbook the same session or
  the rebuild path rots. See `.opencode/rules/iac-required.md`.
- **One-off tasks prohibited** — all work flows through the document lifecycle.
- **Multi-system repo** — never assume a specific host. Check connectivity before infra operations.
- **Hooks auto-setup** — at session start, verify `core.hooksPath` is `.githooks`. If not, run `bash bin/setup-hooks.sh` to ensure consistent commit enforcement across all clones.
- **Document as you go** — every change to infrastructure MUST be recorded in device YAMLs, docs, or vault in the same session. See `.opencode/rules/document-as-you-go.md`.
- **Definition of done** — work isn't done until it's triaged, tested, documented, and stub-free. Machine-enforced (new tool→test, new skill→registered, no stubs) by `bin/definition-of-done-guard.py` in pre-commit + CI; the rest is verified at `endsession`. See `.opencode/rules/definition-of-done.md`.
- **SSH aliases REQUIRED** — never connect by raw IP. Always read `~/.ssh/config` first and use the defined host alias or offer to create a new entry if needed.

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

**Agent context is generated, never committed.** Committed agents/skills/rules stay
environment-agnostic (documentation-range IPs only — pre-commit enforces this). Real
fact sheets live in `environments/<env>/context/` (gitignored), generated from
datasets. See `docs/local-agent-context.md`.

## Tool Scripts (bin/)

All scripts are data-driven — they read from `environments/$ACTIVE_ENV/env.yml`.

| Script | Purpose |
|--------|---------|
| `bin/switch-env.sh <env>` | Set ACTIVE_ENV in `.env`, probe connectivity. **An exported `ACTIVE_ENV` pins a session and wins over `.env`** — use it when two sessions share a clone, or one will change the other's environment mid-task |
| `bin/env-sync.sh <env> <action>` | Sync `environments/<env>/` against its private repo (clone/pull/push/status; map in gitignored `.env-remotes`). Environment layers are single-branch — pull/push refuse from anything but the default branch. `coverage` reports which layers have no remote or unpushed work |
| `bin/check-connectivity.sh [env]` | Probe all connectivity targets from env.yml |
| `bin/ap.sh <playbook>` | Run Ansible playbook with `--limit` scoped to ACTIVE_ENV |
| `bin/open-ticket.sh [subject]` | Manage helpdesk tickets (reads env.yml for prefix/endpoint) |
| `bin/scan.py` | Nmap discovery, enrich YAML device datasets |
| `bin/automation-ladder.py` | Track manual processes → escalate to scripts/playbooks |
| `bin/lifecycle-processor.py` | Manage lifecycle transitions |
| `bin/frappe-exec.py` | Sanctioned Path B Frappe/ERPNext exec (SSH + docker exec + bench venv python); see `frappe-access` skill |
| `mcp/collab-mcp-server.py` | Collaboration-layer self-check: verify every path this file names, report skill/tool drift, propose improvements. **Never edits the governing docs** — run via `bin/mcp-call.py collab --list` |
| `bin/mcp-run.sh` | Launch an `mcp/` server — or an external one declared in `mcp/external-servers.json` — with secrets resolved from the vault (`--check` validates the launch path without fetching anything) |
| `bin/suggest-client-tokens.py` | Report client identifiers found in the private layers that `.client-tokens` does not guard (reports only — never writes; its output is client-identifying, keep it local) |
| `bin/validate-datasets.py` | Validate device records + `env.yml` against `schemas/` (reports by default, `--strict` to fail, `--versions` for schema-version drift) |
| `bin/gen-mikromcp-config.py` | Generate mikromcp's `routers.yaml` from device datasets (`--check` fails on drift, `--env-prefixes` lists the vault-map variables) |
| `bin/mcp-call.py` | Call one MCP tool from a shell via `mcp-run.sh` (`--servers`, `<server> --list`, `--arg`/`--str`). The sanctioned path when an MCP namespace is not loaded. **`--probe` starts every server and reports which cannot actually serve tools** — `mcp-run.sh --check` validates the launch path only |
| `bin/setup-hooks.sh` | Point git at `.githooks` (`--check` for session-start verification) |

## Subagents (invoke with @name)
- `@lifecycle` — lifecycle transitions, proposal→plan→completed
- `@incident` — incident, breach, outage, P1-P4 response
- `@skill-builder` — create/fix/audit OpenCode skills
- `@mikrotik` — RouterOS devices: switches, routers, WiFi APs, CAPsMAN (relay-shell denied, mikromcp only)
- `@linux` — Linux server administration: Ubuntu, Ansible, Docker, Proxmox (mikromcp denied)
- `@security-auditor` — SOC2-oriented Linux security audits: checklist, CVE/vulnerability scanning, findings, remediation (bash gated; reads the mounted `opencode-auditor` member in `projects/`)

Always use `@skill-builder` for new skills — enforces 4-field frontmatter and 60-line limit.

**Domain enforcement:** These agents have runtime-enforced tool permissions. `@mikrotik` has `relay-shell_*` denied and `mikromcp_*` explicitly allowed at the OpenCode runtime level; `@linux` has `mikromcp_*` denied. `@security-auditor` gates all `bash` (`ask`) and denies `mikromcp_*`. Mounted-member subagents (`agents/*.md` reading `projects/<name>/`) are the orchestrator pattern — see `projects/example/README.md`.

Enforcement only exists once the agents are rendered into each harness — the
canonical files live in `agents/`, and both discovery locations
(`.opencode/agent/`, `.claude/agents/`) are **generated and gitignored**:

```bash
python3 bin/automation-ladder.py sync-agents   # then restart the agent session
```

`install.sh` reports when they are missing or stale. Two things to know:

- Tool globs go **directly** under `permission:` in an agent file. A nested
  `permission.tool:` block is silently ignored by OpenCode, so the rules never
  apply — `make test` guards against that shape.
- `mikromcp_*` is denied globally, so an agent that needs it must **explicitly
  allow** it or it gets nothing. Verify with `opencode debug agent <name>`.
- Claude Code cannot hard-enforce deny globs; the rendered files carry the
  intent as an advisory section plus a machine-readable comment. A `PreToolUse`
  hook is the tighter follow-up.

## Skills (load with: opencode tool skill use <name>)
`lifecycle` | `git` | `security` | `backup` | `infra` | `check-connectivity` | `templates` | `tools` | `endsession` | `idea-triage` | `baseline` | `gh` | `helpdesk-ticket` | `frappe-access` | `dogfood-cycle`

Load the relevant skill before working in its domain.

## Two layers — know which one you are changing

This repo contains two different things, and the rules below do not apply equally to
both. Establish which layer you are in *before* citing any principle.

| Layer | What it is | What governs it |
|-------|-----------|-----------------|
| **Product** | What OpsKit does *to environments*: provisioning, devices, services, DNS, records | The Core Rules, the IaC rule, and Development Principle #2's vehicle rule below |
| **Collaboration surface** | The operator, the agent, and the OpsKit CLI between them: this file, `CLAUDE.md`, `skills/`, `agents/`, harness wiring, self-improvement machinery | **Principle #2 does not apply.** No Ansible dimension exists here. The default vehicle is an **MCP tool**, because that is what an LLM reaches for reliably — discoverable, typed schema, harness-agnostic — and `bin/mcp-call.py` makes MCP tools shell-reachable too, so they are strictly more accessible than a script, not less |

**Why this table exists:** an agent applied Principle #2 to a proposal about improving
this very file, concluded "script, not MCP tool", and cited the doctrine as though it
settled the question. It does not — Principle #2 arbitrates how we change *client
environments*. Changing how the operator and the agent work together is a different
layer with different risks. See #136.

One risk specific to the collaboration layer: these files are the **control surface for
agent behaviour**. Verifying them can be automated freely; *rewriting* them cannot — an
automated edit can silently weaken a hard rule and no test catches a rule that has
merely been softened. Tools here propose; a human disposes.

## Development Principles

Set by the project owner; they apply to every session, not per-task.
**Principle #2's vehicle rule governs the product layer** — see the table above.

1. **Never lose an idea.** An idea that surfaces in conversation and isn't acted
   on immediately gets captured before the session ends — cheapest first:
   `bin/idea.py add --desire 1..5 --title "..." --desc "..."` (ledger row in
   `docs/ideas.md`), or an `issues/` file / helpdesk ticket if it's already
   concrete work. Ledger rows become GitHub issues only at triage time — load
   the `idea-triage` skill for that deliberate pass.

2. **Escalate repetition into automation.** Manual work climbs a ladder —
   `bin/automation-ladder.py` measures each rung:
   - A process done by hand **2–3 times** → offer to codify it as a **skill**
   - A skill invoked **more than ~3 times** → offer to replace its manual steps
     with a codified tool. Which vehicle depends on *what kind of state* the
     tool changes:
     - **System/deployment state** — provisioning, packages, services, config
       files, baselines, reset procedures → the tool IS an **Ansible
       playbook/role** in `ansible/` (e.g. `ansible/playbooks/deploy-erp-stack.yml`).
       Plain scripts are only for repo/dev workflow.
     - **Application record state** — API-driven CRUD, queries, relationships
       inside a hosted app → the tool IS an **MCP tool** (e.g.
       `mcp/erpnext-mcp-server.py`'s `erpnext_create_ticket`), or a codified
       CLI where no agent surface is needed. These operations are interactive
       and data-returning, not convergence-shaped, so Ansible models them
       badly — an MCP tool is the correct rung here, not a downgrade to a
       one-off script.
   - A playbook/script that earns heavy use → offer to expose it as a
     **MCP tool** (an agent-facing wrapper over the playbook, distinct from
     the case above where the MCP tool is itself the codification target).
   State lives in `.local/` (gitignored, shared across worktrees).

## Client-Data Isolation (Hard Rule)

**Nothing client-identifying is ever published** — not in tracked files, commit
messages, branch names, GitHub issues, or PR text. Client names, domains,
hostnames, ticket prefixes, and deployment narratives live in the client's
helpdesk and the gitignored `environments/<env>/` layer (lifecycle docs in
`environments/<env>/lifecycle/`, session logs in
`environments/<env>/session-notes/`). GitHub gets the engineering problem,
phrased generically; the helpdesk gets the client. Commit messages reference
tickets as `TKT-<num>` only. Enforced by pre-commit/commit-msg token guards +
`.client-tokens`. Full policy: `docs/client-data-policy.md`.

## Git & GitHub Workflow (Hard Rules)

Set by the project owner (2026-07-20). These apply to every session, no exceptions.

1. **Sync before anything.** Every session starts with `git fetch --all --prune && git pull`
   on the current branch before any other work — avoid conflicts and stale state.
2. **Linked branch per issue.** Work on a GitHub issue NEVER happens directly on `main`.
   Create a linked branch first: `gh issue develop <n> --checkout`. This keeps `main`
   conflict-free and ties the branch to the issue.
3. **Full test gate before completing an issue.** Before an issue is marked ready, run
   full testing of the entire application — `make test` (the same command CI
   runs), `bash -n`/shellcheck on touched scripts, and a functional check of the
   changed behavior — to ensure no regression or new errors were introduced. A failing
   test is fixed, not skipped or deferred; pre-existing unrelated failures get their own
   issue and are named in the PR.
4. **PR conventions.** Once the test cycle is green, open a PR that:
   - references the issue with `Closes #<n>` so merging closes it
   - requests a reviewer **other than the author** (default: `CascadeSTEAM/technology-support`)
   - assigns the author as PR manager (`--assignee @me`)

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

## Incident Recovery

A merged PR that breaks the suite or the tooling → follow `ROLLBACK.md`
(rollback / investigate / hotfix). The post-incident step is mandatory: every
rollback produces a regression test (or guard) and prevention notes.

## Session Artifacts
Both must be updated at session end — do not skip. **Route by session type
(hard rule, see docs/client-data-policy.md "Facts leak too"):**
- Pure public-repo development (issues/PRs/docs): note in
  **`docs/session-notes/`** — commands run, errors, undo instructions —
  plus a **SESSION-LOG.md** strategic entry (decisions, choices, threads).
- Any session touching live infrastructure (client or the org's own),
  including mixed sessions: the operational note goes ONLY in
  **`environments/<env>/session-notes/`** (pushed via `env-sync.sh`);
  the SESSION-LOG entry stays terse and infrastructure-state-free.
  Public notes may describe *code*, never *infrastructure state*.

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
