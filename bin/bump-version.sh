#!/usr/bin/env bash
# bin/bump-version.sh — PR-based version bump with post-merge tagging.
#
# Usage:
#   bin/bump-version.sh <patch|minor|major>    # bump from current version
#   bin/bump-version.sh X.Y.Z                 # exact version
#   bin/bump-version.sh finalize              # tag+push after PR merge
#
# Bump flow:
#   1. Creates release/vX.Y.Z branch, bumps version files, commits
#   2. Pushes the branch and opens a PR via gh
#   3. Prints the PR URL; after merge, run "finalize" to tag+push
#
# Files updated: pyproject.toml, install.sh

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
readonly REPO_ROOT

_usage() {
    echo "Usage:" >&2
    echo "  $0 <patch|minor|major>   bump from current version" >&2
    echo "  $0 X.Y.Z                exact version" >&2
    echo "  $0 finalize             tag+push after PR merge" >&2
    exit 1
}

# ── finalize subcommand ──────────────────────────────────────────────
cmd_finalize() {
    [[ $# -eq 0 ]] && { echo "finalize: missing version argument vX.Y.Z" >&2; exit 1; }
    local TAG_VER="$1"
    # Strip leading v if present
    TAG_VER="${TAG_VER#v}"
    [[ "$TAG_VER" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid version: $TAG_VER" >&2; exit 1; }

    cd "$REPO_ROOT"

    # Must be on main
    local current_branch
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    [[ "$current_branch" == "main" ]] || {
        echo "finalize: not on main branch ($current_branch). Switch to main first." >&2
        exit 1
    }

    # Pull latest main to ensure we have the merged PR
    git switch main && git pull origin main

    # Check tag doesn't already exist
    if git tag -l "v$TAG_VER" | grep -q .; then
        echo "Tag v$TAG_VER already exists." >&2
        exit 1
    fi

    # Create and push the tag
    git tag -a "v$TAG_VER" -m "v$TAG_VER"
    git push origin main --tags

    echo "Done — v$TAG_VER tagged and pushed."
}

# ── bump (default) subcommand ────────────────────────────────────────
cmd_bump() {
    [[ $# -eq 0 ]] && _usage

    local NEW_VER

    if [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        NEW_VER="$1"
    else
        # Read current version from pyproject.toml
        local OLD_VER
        OLD_VER="$(grep '^version = ' pyproject.toml | head -1 | sed 's/.*"\([^"]*\)".*/\1/')"
        local MAJOR MINOR PATCH
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

    local BRANCH="release/v$NEW_VER"
    local TAG="v$NEW_VER"

    cd "$REPO_ROOT"

    # Check we're on main with a clean tree (ignore untracked files)
    local current_branch
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$current_branch" != "main" ]]; then
        echo "Not on main branch ($current_branch). Switch to main and try again." >&2
        exit 1
    fi
    if [[ -n "$(git diff --name-only)" || -n "$(git diff --cached --name-only)" ]]; then
        echo "Working tree is dirty — commit or stash first." >&2
        exit 1
    fi
    if git tag -l "$TAG" | grep -q .; then
        echo "Tag $TAG already exists." >&2
        exit 1
    fi

    echo "Bumping $(grep '^version = ' pyproject.toml | head -1 | sed 's/.*"\([^"]*\)".*/\1/') → $NEW_VER"

    # 1. Update pyproject.toml
    sed -i "s/^version = \".*\"/version = \"$NEW_VER\"/" pyproject.toml

    # 2. Update install.sh (the VERSION= line)
    sed -i "s/^readonly VERSION=\"[^\"]*\"/readonly VERSION=\"$NEW_VER\"/" install.sh

    # 3. Commit the bump
    git add pyproject.toml install.sh
    git commit -m "chore: bump version to $NEW_VER"

    # 4. Create and push the release branch
    git checkout -b "$BRANCH"
    git push -u origin "$BRANCH"

    # 5. Open a PR via gh
    local PR_URL
    PR_URL="$(gh pr create \
        --base main \
        --head "$BRANCH" \
        --title "chore: bump version to $TAG" \
        --body "Automated version bump to $TAG.

- [ ] Merge this PR
- After merge, run \`bin/bump-version.sh finalize $TAG\` to tag and push)" 2>&1)" || {
        echo "Failed to create PR. Branch $BRANCH was pushed — create the PR manually." >&2
        exit 1
    }

    echo ""
    echo "PR created: $PR_URL"
    echo "Merge this PR, then run: bin/bump-version.sh finalize $TAG"
}

# ── dispatch ─────────────────────────────────────────────────────────
[[ $# -eq 0 ]] && _usage

cd "$REPO_ROOT"

if [[ "$1" == "finalize" ]]; then
    shift
    cmd_finalize "$@"
else
    cmd_bump "$@"
fi
