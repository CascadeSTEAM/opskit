---
name: release
description: PR-based version bump with post-merge tagging. Zero flags, no optional modes, PR is the default. USE when the user says /release, /version, version, bump, semver, or asks to cut a release.
mode: skill
triggers: release,version,bump,semver,/version
---

# release

> Bump the project version with one command. PR is the default — tag only after merge.

## Trigger

Load when the user asks to bump versions, cut a release, or types `/release` or `/version`.

## Procedure

1. **Parse version argument:** `bin/bump-version.sh patch|minor|major|X.Y.Z` (default: patch)
2. **Run the bump subcommand** — creates `release/vX.Y.Z` branch, bumps `pyproject.toml` + `install.sh`, commits, pushes, opens PR via `gh`, prints PR URL
3. **Handle the PR merge** — self-merge (`gh pr merge <url> --auto`) or human signoff. Wait for merge.
4. **Finalize:** `bin/bump-version.sh finalize vX.Y.Z` — creates annotated tag and pushes to origin
5. **Report:** "Version bumped to vX.Y.Z and pushed."

## Important

- `bin/bump-version.sh` updates **both** `pyproject.toml` and `install.sh` atomically
- Validates semver, checks for dirty tree on main, verifies tag doesn't exist
- **Tag is created only after the PR is merged** — never before

## Error handling

- **Dirty tree**: "Working tree is dirty — commit or stash first."
- **Not on main**: "Not on main branch. Switch to main and try again."
- **Tag exists**: "Tag vX.Y.Z already exists."
- **Invalid version**: "Invalid version: X.Y.Z"
- **PR creation fails**: Branch name is printed for manual PR creation
