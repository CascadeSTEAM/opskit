# Design: Member Mount — OpsKit-side project sync + agent registration

> **Status:** Final  
> **Created:** 2026-08-25  
> **Owner:** operator  
> **Related:** `docs/opskit-aware.md`, `bin/opskit-aware.py`, `bin/automation-ladder.py`  
> **Idea ledger:** #47 (project-sync.sh mount tooling), #48 (member CLI alias + first adopter)

---

## 1. Problem (unchanged)

A member project declares `pack.yml` saying "I have agents, skills, and docs."
OpsKit has no code to discover, fetch, validate, or mount that member into its
agent/skill discovery paths.

## 2. Goals (unchanged)

1. One CLI surface: `opskit member sync|mount|status`
2. Reuse existing patterns (`.env-remotes` → `.project-remotes`, `sync-agents`)
3. Safe for concurrent sessions (members in external dir, symlinked in)
4. Idempotent (re-run safe, atomic writes)
5. No harness coupling (writes to `.opencode/` / `.claude/` only)

## 3. Architecture

### 3.1 Member discovery: `.project-remotes`

```
# name <url-or-absolute-path> [pin]
example-member ~/Projects/opencode-auditor
security-auditor git@github.com:CascadeSTEAM/opencode-auditor.git v1.0.0
```

Line format: `name path [pin]` where:
- `name` — matches `^[a-z][a-z0-9-]*$`
- `path` — absolute local path (for `symlink` members) or git URL (for `clone` members)
- `pin` — optional SHA/tag (defaults to latest HEAD for `clone`)
- `#` lines are comments; blank lines ignored

File: `REPO_ROOT/.project-remotes` (gitignored, same as `.env-remotes`).

### 3.2 Member disk layout

Members live in `$OPSKIT_MEMBERS_DIR` (default `~/Projects/`), symlinked into
`projects/<name>/` inside OpsKit.

```
$OPSKIT_MEMBERS_DIR/
├── example-member/          ← clone or local checkout
│   ├── .opskit/pack.yml
│   ├── agents/
│   └── skills/

REPO_ROOT/
├── projects/                ← gitignored mount point (symlinks)
│   ├── example-member → ../../Projects/example-member/
│   └── example/             ← committed reference only (not mounted via .project-remotes)
```

**Why external + symlink:** concurrent sessions must never block on git ops,
and a failed clone must not corrupt the shared checkout.

**`projects/example/` is special:** it's a committed reference, NOT a mounted
member. Mount skips it. It exists only so the schema has a testable instance.

### 3.3 CLI commands

| Command | Action |
|---|---|
| `opskit member status` | List all members: mounted, up-to-date, stale, missing |
| `opskit member sync` | Clone/pull members, create/update symlinks |
| `opskit member mount` | Validate pack.yml + render agents/skills into discovery paths |
| `opskit member sync-mount` | sync + mount in one step (session-start) |
| `opskit member pull` | Pull updates for all clone members |

Each outputs JSON to stdout, human-readable to stderr. Exit 0 on partial
success (some members skipped), exit 1 on unrecoverable errors.

### 3.4 What `sync` does

```
for each member in .project-remotes:
    if sync=symlink:
        verify path exists
        if projects/<name>/ doesn't exist: create symlink
    elif sync=clone:
        if $OPSKIT_MEMBERS_DIR/<name>/ doesn't exist: git clone
        else: git pull
    report: mounted | up-to-date | error
```

### 3.5 What `mount` does (data flow)

```
for each mounted member:
    1. opskit-aware.py check <member-root>
       → if validation fails: skip member, report error, continue
    2. render agents
       → for each agent in pack.yml.agents[].path:
         - read agent file from <member-root>/<path>
         - validate agent frontmatter (name, mode required)
         - OpenCode: symlink .opencode/agent/<member>-<agent>.md
           → ../../projects/<member>/agents/<relative-path>
         - Claude Code: generate wrapper .claude/agents/<member>-<agent>.md
           → translates frontmatter dialect, injects trust overlay,
             sets member field in frontmatter
    3. render skills
       → for each skill dir in pack.yml.skills[].path:
         - create symlink .opencode/skills/<member>-<skill>/
           → ../../projects/<member>/<skill>
         - create symlink .claude/skills/<member>-<skill>/
           → same (Claude Code follows symlinks for skills)
    4. prune stale
       → remove rendered agents/skills whose name has no member source
```

### 3.6 Agent rendering strategy

| Harness | Method | Why |
|---|---|---|
| OpenCode | symlink | Live reference, zero re-rendering |
| Claude Code | generated file | Harness doesn't follow symlinks in agents |

**OpenCode symlink:** relative path from `.opencode/agent/` to
`projects/<member>/agents/<file>`. Works because members are in `projects/`.

**Claude Code wrapper** is a generated file that:
1. Translates frontmatter from `mode: subagent` → Claude Code's dialect
2. Injects trust overlay (`bash: ask/allow/deny`, `tool_deny: [...]`)
3. Sets `member: <name>` in frontmatter (indicates origin)
4. Preserves the agent body verbatim

### 3.7 Trust overlay

Read from `pack.yml.trust`:

```yaml
trust:
  bash: ask        # allow | ask | deny
  tool_deny: []    # globs like "mikromcp_*"
```

Applied during mount into the rendered agent's frontmatter:
- `bash: ask` → agent gets `permission.tool.bash: ask` (or overrides existing)
- `tool_deny` → merged with agent's own `permission.tool_deny` (union)

Trust is **additive** — it tightens but never relaxes the agent's own permissions.

### 3.8 Data classification gating

Read from `pack.yml.data_classification`:

| Classification | Mount behavior |
|---|---|
| `public` | Always allowed |
| `internal` | Allowed (warning if opskit has public-facing surface) |
| `client` | Allowed but publication guard will block any public commit |

Mount **warns** on `internal`/`client` but never fails — the operator must
decide. The publication guard (`bin/publication-guard.sh`) handles the actual
enforcement at commit time.

### 3.9 Prune (stale cleanup)

During `mount --prune` (or always, if safe):
- Find rendered agents in `.opencode/agent/` and `.claude/agents/` with prefix
  `<member>-` where no member exists in `.project-remotes`
- Find rendered skills with prefix `<member>-` where no member exists
- Remove stale symlinks/files and report

`--prune` is **always safe** for rendered items (they were created by mount).
Report by default, remove with `--force` or always (configurable).

## 4. Schema updates

### 4.1 `pack.yml` — no changes needed

The existing schema is sufficient. `agents[].path`, `skills[].path`, `trust`,
`data_classification` are all already defined.

### 4.2 Rendered agent frontmatter extension

Rendered agents get an extra field:

```yaml
member: <member-name>
```

This is NOT in the schema — it's added by the renderer, not declared by the
member. Members should not set this field.

## 5. How `opskit member` wraps

The `opskit member init|check` commands already exist via `opskit-aware.py`.
The new commands extend this:

```
opskit member init <path>       ← opskit-aware.py init (already exists)
opskit member check <path>      ← opskit-aware.py check (already exists)
opskit member sync              ← NEW: bin/project-sync.py sync
opskit member mount             ← NEW: bin/project-sync.py mount
opskit member status            ← NEW: bin/project-sync.py status
opskit member sync-mount        ← NEW: sync + mount
opskit member prune             ← NEW: bin/project-sync.py prune
```

## 6. Phases

### Phase 1: `.project-remotes` + `bin/project-sync.py` scan/sync/status

**What:** Read `.project-remotes`, clone/pull members, create/update symlinks,
report status. **Does NOT render agents or skills.**

**Deliverables:**
- `bin/project-sync.py` (executable, python3)
- `.gitignore` entries for `.project-remotes`, `projects/`
- `projects/example/` stays as committed reference
- Tests

**Validation:** `opskit member sync` + `status` works with a local test member.

### Phase 2: `mount` — render agents + skills + prune

**What:** Extend `project-sync.py mount` to call `opskit-aware.py check`,
render agents (symlinks for OpenCode, generated wrappers for Claude Code),
symlink skills, prune stale renders.

**Deliverables:**
- `mount` subcommand with trust overlay
- `sync-agents --members` flag (extends local sync-agents)
- `sync-skills` member scanning
- `prune` logic (inline with mount)
- Atomic writes

**Validation:** Mount `projects/example/` (via `.project-remotes` pointing to
the repo root's `projects/example/` path — or create a test member in
`~/Projects/`).

### Phase 3: `opskit member` CLI + completion

**What:** Wire `opskit member sync|mount|status|sync-mount|prune` in
`bin/opskit` and update completion scripts.

**Validation:** `opskit member sync-mount` works end-to-end.

### Phase 4: First real adopter

**What:** Scaffold `.opskit/` into a real project, mount it, verify.

## 7. Testing strategy

| Test | How |
|---|---|
| `.project-remotes` parsing | Unit test: valid, invalid, empty, comments |
| Clone from git URL | Integration: clone a known repo, verify |
| Symlink from local path | Integration: symlink `~/Projects/opskit/projects/example/` |
| Pull updates | Integration: modify remote, verify pull works |
| Validation failure | Unit: invalid pack.yml → skip member |
| Agent rendering (OpenCode) | Verify symlink target is correct |
| Agent rendering (Claude) | Verify generated file has trust + member fields |
| Skill symlinking | Verify both `.opencode/skills/` and `.claude/skills/` |
| Prune stale | Render, remove from `.project-remotes`, re-mount --prune |
| Atomic write | Kill mount mid-write, verify no corruption |
| Idempotent re-mount | Run mount twice, verify same result |
| `projects/example/` skipped | Verify it's not treated as a mounted member |

## 8. What's deferred (noted, not built)

- `context_generators[]` — no rendering mechanism yet
- `config_fragment` — no application mechanism yet
- `opskit work` (idea #38, single view) — separate command
- Dynamic harness discovery — static rendering is lower common denominator

## 9. Open Questions (resolved during build)

1. **Should `mount` auto-prune stale renders?** Default: yes, always. Stale
   renders from removed members are dead weight. No separate `--prune` flag.
2. **`$OPSKIT_MEMBERS_DIR` default?** `~/Projects/` — mirrors where opsit
   already lives. Overridable via env var or `~/.config/opencode/opencode.json`.
3. **Member agents with `mode` other than `subagent`?** Skip during mount.
   Only `mode: subagent` agents are rendered (same as local sync-agents).
