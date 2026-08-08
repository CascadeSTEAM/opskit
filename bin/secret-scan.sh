#!/usr/bin/env bash
# opskit secret-scan.sh — single source of truth for the grep-based secret
# patterns, shared by the local pre-commit hook and CI (issue #157).
#
# The two used to define their own lists, and CI's was strictly stricter
# (`secret` and `token`, and `[:=]` rather than `=`), so a commit could pass
# every local gate and only fail in CI — the exact round-trip the hook's own
# comment claimed to prevent. Same fix as bin/publication-guard.sh: one script,
# called by both, so the lists cannot drift.
#
# This is the fast keyword scan. It complements, and does not replace, the
# gitleaks pass that both the hook and CI also run.
#
# Usage:
#   bin/secret-scan.sh --cached        # staged changes (pre-commit)
#   bin/secret-scan.sh --tree          # every tracked file of a scanned type (CI)
#   bin/secret-scan.sh --print-patterns  # the patterns themselves (tests)
#
# Override (reviewed false positives only):
#   ALLOW_SECRET_SCAN=1   skip the scan
set -euo pipefail

# OPSKIT_ROOT override exists for tests (point at a temp repo root).
REPO_ROOT="${OPSKIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO_ROOT"

# The union of what the hook and CI checked before, never the intersection —
# collapsing to one list must not loosen either gate.
#
# `[^{]` on the first character: a value starting with a brace is a Jinja or
# JSON placeholder, not a literal credential. Without it the gate fired on
# `password: "{{ some_var }}"`, a false positive that teaches people to reach
# for --no-verify.
PATTERNS=(
    '(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*"[^{][^"]{8,}"'
    '-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----'
    'ghp_[A-Za-z0-9]{36}'
    'AIza[0-9A-Za-z\-_]{35}'
)

# File types the tree scan looks at. The staged scan deliberately checks every
# staged file regardless of extension: a secret committed as `config.local` or
# an extensionless script is still published.
TREE_GLOBS=(
    '*.yml' '*.yaml' '*.py' '*.sh' '*.md'
    '*.json' '*.j2' '*.cfg' '*.toml'
)

# Tracked files only, via git ls-files rather than a filesystem walk. This is a
# publication gate, so untracked content is out of its remit — and walking the
# filesystem locally would read the gitignored environments/ layer, which holds
# REAL client credentials. A scan that prints those to a terminal or a CI log to
# warn about secrets would be the leak it exists to prevent.
tree_files() {
    local globs=()
    local g
    for g in "${TREE_GLOBS[@]}"; do globs+=(":(glob)**/$g" ":(glob)$g"); done
    git ls-files -z -- "${globs[@]}"
}

if [ "${1:-}" = "--print-patterns" ]; then
    printf '%s\n' "${PATTERNS[@]}"
    exit 0
fi

if [ "${ALLOW_SECRET_SCAN:-}" = "1" ]; then
    echo "NOTE: secret scan skipped (ALLOW_SECRET_SCAN=1)."
    exit 0
fi

MODE="${1:-}"
case "$MODE" in
    --cached|--tree) ;;
    *) echo "usage: secret-scan.sh --cached | --tree | --print-patterns" >&2; exit 2 ;;
esac

if [ "$MODE" = "--cached" ]; then
    # Staged content, not the worktree: what is about to be committed is what
    # must be clean. --diff-filter=ACM skips deletions.
    file_list() { git diff --cached --name-only --diff-filter=ACM -z; }
else
    file_list() { tree_files; }
fi

matches=""
for pattern in "${PATTERNS[@]}"; do
    # -e is load-bearing, not style: the PRIVATE KEY pattern starts with '-',
    # so without it grep parses the pattern as options, fails with
    # "unrecognized option", and `|| true` swallows that into a silent pass.
    # The hook carried that bug from the start — its private-key check had never
    # matched anything (found by the test suite for #157).
    #
    # -I skips binary files; a match inside one is noise, not a finding.
    hit=$(file_list | xargs -0 -r grep -InE -e "$pattern" 2>/dev/null || true)
    [ -n "$hit" ] && matches="$matches$hit"$'\n'
done

if [ -n "$(printf '%s' "$matches" | tr -d '[:space:]')" ]; then
    echo "ERROR: possible secret detected:" >&2
    printf '%s' "$matches" >&2
    echo "Remove the secret, or use a placeholder value, and try again." >&2
    echo "Reviewed false positive? ALLOW_SECRET_SCAN=1 (discouraged)." >&2
    exit 1
fi

echo "PASS: no secrets found ($MODE)."
