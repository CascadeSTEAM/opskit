# Workstation installation

How to stand up a **fully capable** opskit workstation — one where `make test`
passes, the pre-commit guards run, playbooks execute, and the domain subagents
can actually reach devices through their sanctioned tool paths.

## Quick start (recommended)

```bash
# 1. Clone the repo
git clone <opskit remote> $HOME/Projects/opskit
cd $HOME/Projects/opskit

# 2. Run the installer — interactive wizard on TTY, diagnostic in a pipe
bash install.sh
```

`install.sh` is **idempotent**: re-running it skips what's already done and
reports what's missing. On TTY it launches a **wizard** that walks you through
each step in plain language; in a pipe or with `--check` it runs diagnostic
only.

| Flag | Behaviour |
|------|-----------|
| *(none, TTY)* | Interactive wizard — step by step |
| `--auto` | Non-interactive — skips done, auto-approves |
| `--check` | Diagnostic only — reports state, installs nothing |
| `--quick` | Installs only missing `apt` packages |
| `--refresh` | Wipes state, reinstalls everything |

State lives in `~/.opskit-install/state/` (safe to delete).

At the end, the installer lists **manual steps** (SSH config, vault access,
environment clone) with copy-paste commands — these require your credentials
and cannot be automated.

For a fully capable workstation, the wizard guides you through these layers:

| Layer | What it installs |
|-------|-----------------|
| 1. CLI tools | `curl`, `git`, `sudo`, `unzip`, `xclip` (apt) |
| 2. Python 3 + pip | `python3`, `python3-venv`, `python3-pip` |
| 3. Ansible | `ansible-core` in an isolated venv (`~/.local/opskit-ansible`) |
| 4. OpsKit CLI | Symlink of `bin/opskit` into `~/.local/bin` |
| 5. MCP setup | Scaffold + credential guidance (vault required) |

Layers 1–4 are automated. Layer 5 and everything in §§6–7 below requires
credentials that must be provided manually.

## What "installed" means

Installation is five separable layers. You can stop after any of them; each
one buys a specific capability.

| Layer | You get | Without it |
|-------|---------|------------|
| 1. Base tooling | `opskit` CLI, scanning, schema validation | nothing works |
| 2. Test & commit gate | `make test`, `make lint`, pre-commit guards | you cannot safely commit |
| 3. Ansible | playbook execution via `bin/ap.sh` | no IaC — the mandated path for system state |
| 4. Agent runtime + MCP | domain subagents with real device access | agents can advise but not act |
| 5. Environment data | your actual devices, credentials, tickets | env-agnostic toolkit with no environments |

Layers 1–3 are reproducible from this repo alone. Layers 4 and 5 require
material that is deliberately **not** in git — see §6 and §7.

## Manual install (advanced)

If you prefer to install each layer by hand, or need a non-standard setup,
the sections below document each layer and its dependencies in detail.
For most users, `bash install.sh` replaces these sections entirely.

---

---

## 1. Base tooling (required)

```bash
sudo apt install -y git python3 python3-venv python3-pip nmap \
                    openssh-client curl jq make
```

- **Python ≥ 3.12** — `pyproject.toml` sets `requires-python = ">=3.12"`.
- **nmap** — the discovery phase of `opskit scan` shells out to it.
- **openssh-client** — every remote path goes through SSH host aliases
  (`AGENTS.md`: never connect by raw IP).

Python packages for the CLI itself:

```bash
python3 -m pip install --user pyyaml jsonschema
```

Then link the CLI and install completions:

```bash
bash install.sh
```

This symlinks `bin/opskit` into `~/.local/bin`. Make sure that directory is on
your `PATH`.

---

## 2. Test and commit gate (required for contributors)

```bash
make deps     # builds .venv from requirements-dev.txt
make test     # the exact command CI runs
```

`requirements-dev.txt` is the single dependency list shared by local runs and
CI so the two cannot drift: `pytest`, `pyyaml`, `jsonschema`, `requests`, `mcp`.

Git hooks are **not** active in a fresh clone — `core.hooksPath` is repo-local
config, not something git clones:

```bash
bash bin/setup-hooks.sh             # configure (idempotent — safe every session)
bash bin/setup-hooks.sh --check     # report only; non-zero if guards are inactive
```

`AGENTS.md` requires verifying this at session start. `--check` is the
scriptable form.

The hooks call two external binaries. Both degrade gracefully when absent, but
that means a fresh workstation silently runs a weaker check than CI:

| Tool | Used by | If missing |
|------|---------|------------|
| `gitleaks` | pre-commit deep secret scan | hook skips it; **CI still fails you** |
| `shellcheck` | `make lint` | syntax-only checking |

`shellcheck` is in apt. `gitleaks` is not — install the release binary:

```bash
sudo apt install -y shellcheck
# gitleaks: download the latest linux_x64 tarball from
#   https://github.com/gitleaks/gitleaks/releases
# and place the binary in /usr/local/bin
```

Verify the guards work before you trust them:

```bash
make lint
make guard      # publication guards against staged changes
```

---

## 3. Ansible (required for infrastructure work)

Ansible is the mandated vehicle for all repeatable system and deployment state
(`AGENTS.md` → IaC mandatory). Install it isolated, not into system Python:

```bash
sudo apt install -y pipx
pipx install --include-deps ansible
pipx install ansible-lint
```

Then rehydrate the collections. `ansible.cfg` sets
`collections_path = ./`, and `ansible_collections/` is gitignored — so **every
fresh clone starts with zero collections** and playbooks fail on unresolved
modules until you run:

```bash
ansible-galaxy collection install -r requirements.yml
```

That installs `ansible.posix`, `community.general`, and `community.routeros`.

---

## 4. Node runtime (required for the device-facing MCP servers)

The router/switch tool path and the credential CLI are both Node packages.
Install a Node 22 line — nvm keeps it out of system package management:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/master/install.sh | bash
nvm install 22
```

Then:

```bash
npm install -g mikromcp @bitwarden/cli
```

| Package | Provides | Why it matters |
|---------|----------|----------------|
| `mikromcp` | `mikromcp_*` tools | **The only sanctioned path to RouterOS gear.** Direct SSH to that hardware is denied at runtime, so without this binary the router/switch/AP subagent has no way to act at all. |
| `@bitwarden/cli` | `bw` | Every MCP wrapper script resolves its secrets through `bw`. No `bw`, no credentials, anywhere. |

`npx` (bundled with npm) must also be reachable — one MCP server is launched
through it rather than being installed globally.

Repo-local Node deps for the agent integration layer:

```bash
cd .opencode && npm install && cd ..
```

---

## 5. `uv` (required for the Python-packaged MCP servers)

Some MCP servers are distributed as `uvx`-runnable packages rather than being
vendored here. Install it via the playbook, not the vendor's curl-pipe —
control-node software lands via IaC (`.opencode/rules/iac-required.md`):

```bash
# On a workstation already in a `workstations` inventory group:
bash bin/ap.sh playbooks/workstation-mcp-toolchain.yml

# Bootstrap — a fresh workstation is in no inventory yet, which is exactly
# when this needs to run:
ansible-playbook -i "$(hostname)," -c local -e target="$(hostname)" \
  ansible/playbooks/workstation-mcp-toolchain.yml
```

This installs `uv` through pipx in user scope, no root, and is idempotent —
re-running reports `changed=0`. Rollback is `pipx uninstall uv`.

`uv` and `uvx` are separate console scripts from the same package; the
playbook verifies both resolve and that `uvx` is on `PATH`, because `uvx` is
the entry point the MCP server definitions actually invoke.

Without it, those servers fail to start and their tool namespaces are simply
absent from the agent session — which reads as the agent declining to use
them, not as a broken install.

> The playbook drives `pipx` through its CLI rather than the
> `community.general.pipx` module: that module requires pipx ≥ 1.7.0 and fails
> with a bare version error on anything older, and the current Ubuntu LTS
> ships 1.4.3. Worth knowing, because
> `workstation-ansible-toolchain.yml` *does* use the module and will fail the
> same way on a stock workstation.

---

## 6. Agent runtime and MCP wiring

This is the layer that turns opskit from a set of scripts into the subagent
capability. None of it lives in this repo — it is user-level configuration.

### 6.1 Runtimes

Install the agent runtime(s) you use. The domain subagents in `agents/`
(`@mikrotik`, `@linux`, `@lifecycle`, `@incident`, `@skill-builder`) carry
runtime-enforced tool permissions — the deny rules in their frontmatter are
what make "RouterOS only through its MCP server" an enforced boundary rather
than a suggestion. Those permissions are honoured by the OpenCode runtime, so
that runtime is what you install to get the enforcement.

### 6.2 The standing instruction

The global agent memory file that routes *all* infrastructure work to opskit is
user-level, outside this repo. Copy it from your existing workstation:

```
~/.claude/CLAUDE.md
```

Nothing in this repo reproduces it. Without it, an agent on the new machine
will happily re-derive infrastructure by hand instead of using the toolkit.

### 6.3 Runtime configuration

Copy the runtime config directory from the existing workstation:

```
~/.config/opencode/
```

It carries four things you cannot regenerate:

1. **Model providers** and the fallback plugin.
2. **The permission deny-map** — the per-namespace denials backing domain
   isolation.
3. **The `mcp` block** — how every MCP server is launched.
4. **Global agents and skills** kept outside the repo.

### 6.4 MCP servers

The `mcp` block references launcher scripts and checkouts by **absolute path**.
Every one of those paths must exist on the new machine or that server fails to
start. Audit the block and satisfy each entry:

| Kind | What to install |
|------|-----------------|
| Globally installed binary | covered by §4 |
| `npx`-launched | covered by §4 |
| `uvx`-launched | covered by §5, plus any config file the entry points at |
| Wrapper script in a sibling repo | clone that repo **and build its own virtualenv** — the wrappers exec their repo's `.venv/bin/python3`, not yours |
| Node server in a sibling repo | clone **and build it** — the config points at compiled output under `dist/`, which is not committed |

For the servers **this repo owns** (`mcp/*-mcp-server.py`), do not write a
wrapper — use the launcher:

```bash
bin/mcp-run.sh --list                  # servers this repo provides
bin/mcp-run.sh <server> --check        # validate the launch path, fetch nothing
bin/mcp-run.sh <server>                # resolve secrets from the vault, exec the server
```

Point the runtime config at `bin/mcp-run.sh <server>`. Secrets are declared in
a gitignored `mcp/vault-map.local.json` mapping each env var to a vault
item/field — copy `mcp/vault-map.example.json` and fill it in. Nothing tracked
in this repo contains a vault identifier or a tenant name.

> **Check for drift while you migrate.** Wrapper scripts in sibling repos can
> point at an *older copy* of a server this repo has since superseded. Before
> copying the config verbatim, diff each wrapper's target against `mcp/` and
> repoint it at `bin/mcp-run.sh` if this repo's copy is newer. Migrating is the
> cheapest moment to collapse that duplication.

Every launch path aborts unless a vault session is available. Either source
works; the environment variable wins when both are present:

```bash
export BW_SESSION=$(bw unlock --raw)                    # this shell only

mkdir -p ~/.cache/opskit                                # persists across shells
(umask 077; bw unlock --raw > ~/.cache/opskit/bw-session)
```

Write it inside `(umask 077; …)` rather than chmod'ing afterwards: a plain
redirect creates the file at your default umask, leaving a live key to the
whole vault group-readable until the chmod lands.

Export it **before** starting the agent runtime — servers read the variable at
launch, so unlocking afterwards does not help the current session.

The session file (path overridable with `BW_SESSION_FILE`) exists so a
credentialed shell call needs no `BW_SESSION=…` prefix: `bin/mcp-call.py …`
alone works, which lets a permission allow-rule cover the sanctioned MCP path
(prefix-matched rules cannot see past a leading assignment). The file is
refused if it is readable beyond its owner — a session token is a live key to
every secret in the vault.

`--check` is the fast diagnosis for a missing tool namespace: it reports the
venv, the server file, the vault map, the CLI, the session, and how many
secrets are declared, without touching the vault or a live endpoint.

---

## 7. Secrets and state — cannot be installed

None of the following is in git, by design (`docs/client-data-policy.md`).
Each must be re-established on the new workstation.

### 7.1 Vault access

Log in to the vault backend and unlock it (§6.4). This gates every credential
in the system.

### 7.2 SSH configuration

`~/.ssh/config` and the private keys it references. Host aliases are
**load-bearing**, not a convenience: connecting by raw IP is prohibited, and
playbook inventories and topology resolution both refer to devices by alias.
Copy the config and every `IdentityFile` it names, then `chmod 600` the keys.

### 7.3 Environment repositories

`environments/*` is gitignored except `example/`. Real environments live in
their own private repos, mapped in the gitignored `.env-remotes` file.

If the old workstation is reachable, copy that file across. If it is not —
lost, decommissioned, disk failure — restore it from its Vaultwarden backup
instead (§6.4 for unlocking the vault):

```bash
bash bin/env-sync.sh restore-remotes
```

That only works if `backup-remotes` was ever run from a surviving
workstation (`docs/environment-storage.md` §2) — it is not automatic, and a
`.env-remotes` that was never backed up is unrecoverable by either path.

Either way, then clone each environment:

```bash
bash bin/env-sync.sh <env> clone
```

Audit the result: **an environment directory with no entry in `.env-remotes`
exists only on the old machine** and will be lost unless you copy it manually
or give it a remote first. Check for that before you decommission anything.

### 7.4 Local state files

All gitignored; copy from the old workstation:

| File | Holds |
|------|-------|
| `.env` | the active environment selection |
| `.env-remotes` | environment → private repo map |
| `.client-tokens` | the publication guard's token list |
| `mcp/*.local.json` | per-tenant MCP endpoint configuration |
| `.current-ticket` | in-flight ticket (regenerated by `bin/open-ticket.sh`) |

### 7.5 GitHub access

```bash
gh auth login
```

Required by `bin/fix-issue.sh`, the issue/PR workflow in `AGENTS.md`, and any
remote MCP server that authenticates as you.

---

## 8. Verification

Run these in order. Each one gates the next.

```bash
bash install.sh --check             # dependency preflight (or just: bash install.sh)
bash bin/setup-hooks.sh --check     # commit guards active
opskit check                        # core deps + hooks + environments
make test                           # the CI gate
make lint                           # shell syntax + shellcheck
bash bin/switch-env.sh <env>        # select environment, probe connectivity
bash bin/check-connectivity.sh      # reachability for every probe in env.yml
ansible-galaxy collection list      # the three collections resolve
uv --version && uvx --version       # uvx-distributed MCP servers can start
```

Then verify the agent layer, which none of the above touches:

1. Export a vault session and start the agent runtime.
2. Confirm each expected MCP tool namespace is present. A server whose path is
   wrong fails **silently** at startup — its tools are simply missing, which
   reads like "the agent chose not to use it."
3. Exercise one read-only tool per namespace.

---

## 9. Failure modes and what they mean

| Symptom | Cause |
|---------|-------|
| Playbook fails on an unresolved module | collections not rehydrated (§3) |
| Commit succeeds locally, CI secret scan fails | `gitleaks` missing locally (§2) |
| Commit rejected for a missing ticket reference | no active environment or ticket — run `switch-env.sh` then `open-ticket.sh` |
| A whole MCP tool namespace is absent | server failed at launch: bad path, missing checkout, unbuilt `dist/`, or missing `.venv` (§6.4) |
| Only the `uvx`-launched servers' tools are absent | `uv` not installed, or `uvx` not on `PATH` (§5) |
| Every MCP server fails at once | no `BW_SESSION` exported before the runtime started (§6.4) |
| Router/switch work has no available tool path | `mikromcp` not installed — direct SSH is denied by design, so there is no fallback (§4) |
| `opskit` not found after install | `~/.local/bin` not on `PATH` |
| Tests pass, `make lint` finds nothing | `shellcheck` not installed — syntax-only (§2) |

---

## 10. Quick reference

Shortest correct order for a new workstation:

```bash
# 1. base (installer handles most of this)
sudo apt install -y git python3 python3-venv python3-pip nmap \
                    openssh-client curl jq make shellcheck pipx
#    + gitleaks binary → /usr/local/bin

# 2. runtimes
nvm install 22 && npm install -g mikromcp @bitwarden/cli
pipx install --include-deps ansible && pipx install ansible-lint

# 3. repo + installer
git clone <opskit remote> && cd opskit
bash install.sh                         # wizard or: bash install.sh --auto
bash bin/setup-hooks.sh
make deps
ansible-galaxy collection install -r requirements.yml
(cd .opencode && npm install)
ansible-playbook -i "$(hostname)," -c local -e target="$(hostname)" \
  ansible/playbooks/workstation-mcp-toolchain.yml     # uv/uvx

# 4. user-level config + secrets (copied from the old workstation)
#    ~/.claude/CLAUDE.md, ~/.config/opencode/, ~/.ssh/
#    .env, .env-remotes, .client-tokens, mcp/*.local.json
gh auth login
export BW_SESSION=$(bw unlock --raw)

# 5. environments + verify
bash bin/env-sync.sh <env> clone
bash install.sh --check && opskit check && make test
```
