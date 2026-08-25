#!/usr/bin/env bash
# bin/bump-version.sh — bump version in all places and create the git tag.
#
# Usage:
#   bin/bump-version.sh patch    # 0.2.1 → 0.2.2
#   bin/bump-version.sh minor    # 0.2.1 → 0.3.0
#   bin/bump-version.sh major    # 0.2.1 → 1.0.0
#   bin/bump-version.sh 0.3.0    # exact version
#
# Files updated: pyproject.toml, install.sh
# Then: commits the bump and creates the git tag.

set -euo pipefail
readonly REPO_ROOT="$(git rev-parse --show-toplevel)"

_usage() {
    echo "Usage: $0 <patch|minor|major|X.Y.Z>" >&2
    exit 1
}

[[ $# -eq 0 ]] && _usage

cd "$REPO_ROOT"

# Parse version
if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    NEW_VER="$1"
else
    # Read current version from pyproject.toml
    OLD_VER="$(grep '^version = ' pyproject.toml | head -1 | sed 's/.*"\([^"]*\)".*/\1/')"
    IFS='.' read -r MAJOR MINOR PATCH <<< "$OLD_VER"
    case "$1" in
        patch) NEW_VER="$MAJOR.$MINOR.$((PATCH + 1))" ;;
        minor) NEW_VER="$MAJOR.$((MINOR + 1)).0" ;;
        major) NEW_VER="$((MAJOR + 1)).0.0" ;;
        *) _usage ;;
    esac
fi

# Validate semver
[[ "$NEW_VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid version: $NEW_VER" >&2; exit 1; }

# Check we're on a clean working tree
if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree is dirty — commit or stash first." >&2
    exit 1
fi

# Check tag doesn't already exist
if git tag -l "v$NEW_VER" | grep -q .; then
    echo "Tag v$NEW_VER already exists." >&2
    exit 1
fi

echo "Bumping $OLD_VER → $NEW_VER"

# 1. Update pyproject.toml
sed -i "s/^version = \".*\"/version = \"$NEW_VER\"/" pyproject.toml

# 2. Update install.sh (the VERSION= line)
sed -i "s/^readonly VERSION=\"[^\"]*\"/readonly VERSION=\"$NEW_VER\"/" install.sh

# 3. Commit and tag
git add pyproject.toml install.sh
git commit -m "chore: bump version to $NEW_VER"
git tag -a "v$NEW_VER" -m "v$NEW_VER"

echo "Done — pushed with: git push origin main && git push origin --tags v$NEW_VER"
