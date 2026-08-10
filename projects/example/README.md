# projects/ — mounted member repos

The orchestrator mounts related repos here as domain subagents. Each member is
synced into `projects/<name>/` (gitignored — real members never enter this
public repo); only this `example/` reference is committed.

A member contributes domain **knowledge** (docs) plus one or more **subagent
definitions** that read that knowledge at runtime, rather than copying it into
opskit. No member is mounted today — the pattern below is worked but unused
until a domain subagent actually needs one.

## MVP mount (local)

```bash
ln -s ~/Projects/<member-repo> projects/<member-name>
python3 bin/automation-ladder.py sync-agents   # render the subagent into both harnesses
```

Map real members in the gitignored `.project-remotes` (one
`<name> <git-url-or-abs-path>` per line, `#` comments allowed), mirroring
`.env-remotes`. The schema'd `.opskit/pack.yml` manifest and `bin/project-sync.sh`
(clone/pull/status/mount) land in the next phase.

## Rules for a member

- Contributes documentation-range, environment-agnostic knowledge only. Real
  facts (hosts, findings) never live in a member or in opskit — they stay in
  the gitignored `environments/<env>/` layer (`docs/client-data-policy.md`).
- Its subagent reads member docs at runtime via `projects/<name>/...`; it must
  not duplicate that content into `agents/`.
- Sandbox the subagent with `permission` in its `agents/*.md` definition.
- If a member's own docs describe a dual-use or destructive procedure (e.g. a
  credential-recovery skill), the mounting subagent's `agents/*.md` MUST write
  down an explicit per-invocation approval gate for it — the member's docs are
  not themselves a safety control, and nothing else in this repo enforces one.
  A prior mount (`opencode-auditor`/`@security-auditor`, removed #193) carried
  exactly this gate for a RustDesk stored-password recovery skill; re-add it
  in whatever subagent mounts that member again, don't assume it's implied.
