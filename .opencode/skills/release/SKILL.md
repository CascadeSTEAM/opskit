---
name: release
description: Bump version, tag, and push. Use when the user says /version, /release, version, bump, semver, or asks to cut a release.
mode: skill
triggers: release,version,bump,semver,/version
---

# release

> Bump the project version with one command. Never edit version files by hand.

## Trigger

Load this skill whenever the user asks to bump versions, cut a release, or types `/version`.

## Procedure

1. Verify clean working tree:
   ```bash
   git status --porcelain
   ```
   If dirty, tell the user to commit first.

2. Parse the version argument:
   ```bash
   bin/bump-version.sh patch   # 0.2.1 → 0.2.2
   bin/bump-version.sh minor   # 0.2.1 → 0.3.0
   bin/bump-version.sh major   # 0.2.1 → 1.0.0
   bin/bump-version.sh 0.5.0   # exact version
   ```

   If the user says `/version patch` or just `patch`, run the patch command.
   If the user says `/version 0.5.0` or just `0.5.0`, run the exact version command.
   If no argument is given, default to `patch` and confirm.

3. After the script runs, it prints the push command. Execute:
   ```bash
   git push origin main && git push origin --tags
   ```

4. Report the result to the user:
   ```
   Version bumped to v0.2.2 and pushed.
   ```

## Important

- `bin/bump-version.sh` updates **both** `pyproject.toml` and `install.sh` atomically
- It validates semver, checks for dirty tree, and verifies the tag doesn't exist
- If the tag already exists, it refuses and tells the user
- The script always leaves `git push` as a manual step so the user can review the commit first

## Error handling

- **Dirty tree**: "Working tree is dirty — commit or stash first."
- **Tag exists**: "Tag vX.Y.Z already exists."
- **Invalid version**: "Invalid version: X.Y.Z"
