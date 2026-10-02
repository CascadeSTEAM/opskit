# 2026-08-25 — /release PR-based redesign (issue #262)

Pure public-repo development: skill rewrite, script refactor, command scaffold, PR
opened. No live infrastructure touched.

## What ran

`git fetch --all --prune && git pull` on `release-skill-session`, then three-phase
implementation of issue #262:

1. Refactored `bin/bump-version.sh` — bump subcommand creates `release/vX.Y.Z`
   branch, opens PR; `finalize` subcommand runs after merge to tag+push
2. Rewrote `.opencode/skills/release/SKILL.md` for PR-based flow
3. Created `.opencode/command/release.md` via `bin/gen-command --force --auto`

## Merged

| PR | Issue | Summary |
|---|---|---|
| #263 | #262 | PR-based version bump with post-merge tagging |

## Changes

### `bin/bump-version.sh`

- Bump subcommand: verifies clean tree on main, bumps `pyproject.toml` + `install.sh`,
  creates `release/vX.Y.Z` branch, pushes, opens PR via `gh pr create`
- `finalize <version>` subcommand: switches to main, pulls latest, creates annotated
  tag, pushes tag to origin
- Zero `--` flags, zero optional modes, PR is the default

### `.opencode/skills/release/SKILL.md`

- 36 lines (under 60-line limit)
- 5-step procedure: parse → bump → merge PR → finalize → report
- Supports self-merge and human signoff review modes

### `.opencode/command/release.md`

- New skill-loader scaffold (created via `bin/gen-command --force --auto`)
- Description consistent with skill frontmatter

## Errors and near-misses

**`gh pr edit --title` silently ignored the title change.** The `--title` flag on
`gh pr edit` appeared to succeed (no error) but the PR title remained the old value.
Resolved via the GitHub REST API directly: `gh api repos/CascadeSTEAM/opskit/pulls/263
--method PATCH -f title=...`.

**Reviewer self-assign blocked.** GitHub does not allow a PR author to request their
own review. Used `gh api` to request review from the `technology-support` team instead,
which succeeded.

## Testing

- `bash -n bin/bump-version.sh` — passes
- `bin/gen-command --check release` — PASS (all checks green)
- `make test` — 1066 passed, 1 skipped, 1 pre-existing failure in `test_bw_session.py`
  (`install.sh` doesn't use `bw_session.py` — unrelated to this change)
- `python3 bin/definition-of-done-guard.py --cached` — no modified files (changes on
  `release-skill-session` branch)
- `python3 bin/gen-mikromcp-config.py --check` — OK
- `python3 bin/automation-ladder.py sync-agents` — regenerated both harness targets

## Practice that paid off

Code review was done inline against the PR diff (`git diff main`) before pushing —
verified the dispatch guard logic (`[[ $# -eq 0 ]] && _usage`) was already correct
before attempting to "fix" it.

## Undo

PR #263 can be reverted with `git revert` on `main` once merged. For the unreleased
local work: branch is `release-skill-session`, no local uncommitted changes.
