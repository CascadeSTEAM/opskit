# Making a project OpsKit-aware

OpsKit can drive and develop related projects as **subagents**: a project's
domain knowledge (docs) and any subagent/skill definitions are mounted read-only
into an OpsKit session, sandboxed, and selected by the master AI when a task
matches. A project opts into this by declaring a small, versioned manifest — it
becomes *OpsKit-aware*.

This is additive: the manifest never changes how the project works on its own.

## What a member ships

A member repo carries a `.opskit/` folder:

```
<member-repo>/
  .opskit/
    pack.yml     # the manifest (machine-readable contract)
    README.md    # human/agent-facing blurb, links back to the public OpsKit repo
```

`pack.yml` fields (full contract: `schemas/project.schema.json`):

| Field | Meaning |
|---|---|
| `contract` | Manifest contract version (currently **1**). Bumped when the contract changes, so stale members fail `check` instead of drifting. |
| `name` | Member name (`^[a-z][a-z0-9-]*$`); becomes `projects/<name>/` when mounted. |
| `description` | One line: what the member contributes as a subagent. |
| `data_classification` | `public` \| `internal` \| `client` — sensitivity of the member's own tracked content; gates OpsKit's publication guard at mount. |
| `sync` | `clone` (a git remote) \| `symlink` (a local checkout, for development). |
| `url`, `pin` | Optional: git URL / SHA-or-tag for `sync: clone` (`url` may instead live only in OpsKit's gitignored `.project-remotes`). |
| `agents[]` | Member-relative paths to `agents/*.md` subagent definitions. |
| `skills[]` | Member-relative paths to skill directories (each containing `SKILL.md`). |
| `docs[]` | Member-relative methodology docs a mounting subagent reads at runtime. |
| `config_fragment` | Optional harness config/permission overlay. |
| `context_generators[]` | Optional scripts that render env-local fact sheets. |
| `trust` | Sandbox defaults applied on mount: `bash` (`allow`\|`ask`\|`deny`) and `tool_deny[]` globs. |

## Adopt it (one command)

From an OpsKit checkout, scaffold the manifest into any project — it auto-detects
`agents/`, `skills/` (or `.opencode/skills/`), and `docs/`:

```bash
python3 <opskit>/bin/opskit-aware.py init /path/to/your-project
# edit the TODOs in .opskit/pack.yml, prune what doesn't apply, then:
python3 <opskit>/bin/opskit-aware.py check /path/to/your-project
```

`projects/example/` in the OpsKit repo is a committed, `check`-able reference.

## Keep it aligned (good hygiene)

The contract is versioned, and the same `check` runs on both sides — so drift is
caught mechanically rather than discovered at mount time:

- **In the member's own CI** — fail the build if `pack.yml` drifts. If OpsKit
  isn't available in that CI, validate against the published schema directly:

  ```bash
  pip install check-jsonschema
  curl -fsSL https://github.com/CascadeSTEAM/opskit/raw/main/schemas/project.schema.json \
    -o /tmp/project.schema.json
  check-jsonschema --schemafile /tmp/project.schema.json .opskit/pack.yml
  ```

  (Schema-only; add `opskit-aware.py check` when OpsKit is available to also
  verify referenced paths exist.)
- **In OpsKit** — `check` re-runs before a member is mounted.

## Rules for members

- Contribute **documentation-range, environment-agnostic** knowledge only. Real
  facts — hostnames, secrets, findings — never live in a member or in OpsKit;
  they stay in OpsKit's gitignored `environments/<env>/` layer
  (`docs/client-data-policy.md`).
- **Sandbox** each subagent in its `agents/*.md` frontmatter and via `trust`.
- If a member's docs describe a **dual-use or destructive** procedure, the
  mounting subagent MUST gate it behind explicit per-invocation approval — the
  docs are not themselves a safety control.

## How the pieces fit

`agents/*.md` are rendered into both harnesses by
`bin/automation-ladder.py sync-agents`; members are mounted under `projects/`
(see `projects/example/README.md`). `opskit-aware.py` is the member-facing half
(declare + validate); OpsKit-side mount/sync tooling (`project-sync`) is tracked
separately.
