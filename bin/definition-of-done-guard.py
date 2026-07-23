#!/usr/bin/env python3
"""definition-of-done-guard.py — enforce the opskit "definition of done".

Mechanically blocks the failure class where a change ships half-finished:
a new tool with no test, a new skill nobody registered, or a stub left in
shipped code. Runs identically in the pre-commit hook (staged changes) and in
CI (branch diff), so local and server-side enforcement cannot drift — the same
pattern bin/publication-guard.sh uses.

Full policy: .opencode/rules/definition-of-done.md

Usage:
    definition-of-done-guard.py --cached          # staged changes (pre-commit)
    definition-of-done-guard.py <git-range>       # e.g. origin/main...HEAD (CI)

Per-file opt-out (use sparingly, with a reason on the same line):
    # dod: no-test  — this bin/ script is genuinely not unit-testable

Whole-run escape hatch (discouraged; leaves a reason in the output):
    ALLOW_DOD_SKIP=1
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or SCRIPT_DIR.parent)

# Phrases that mean "not finished" and must not reach a shipped code file.
STUB_MARKERS = [
    "not yet implemented",
    "not implemented yet",
    "todo: implement",
    "fixme: implement",
]
# Only these extensions are scanned for stub markers (code, not prose).
CODE_SUFFIXES = {".py", ".sh"}


def changed_files(range_or_cached: str) -> list:
    """Return [(status, path)] for added/modified/renamed files in the change set."""
    if range_or_cached == "--cached":
        cmd = ["git", "diff", "--cached", "--name-status", "--diff-filter=ACMR"]
    else:
        cmd = ["git", "diff", "--name-status", "--diff-filter=ACMR", range_or_cached]
    out = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True).stdout
    files = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]  # A, M, R
        path = parts[-1]  # for renames, the new path is last
        files.append((status, path))
    return files


def test_name_for(stem: str) -> str:
    """bin/env-sync.sh -> test_env_sync.py (dashes normalise to underscores)."""
    return f"test_{stem.replace('-', '_')}.py"


def check_new_tool_has_test(files: list, errors: list):
    for status, path in files:
        if status != "A" or not path.startswith("bin/") or not path.endswith(".py"):
            continue
        name = Path(path).name
        if name == "__init__.py":
            continue
        full = REPO_ROOT / path
        if full.exists() and "dod: no-test" in full.read_text():
            continue
        expected = test_name_for(Path(path).stem)
        if not (REPO_ROOT / "tests" / expected).exists():
            errors.append(
                f"{path}: new tool has no test — add tests/{expected} "
                f"(or mark it '# dod: no-test' with a reason if genuinely untestable)."
            )


def check_new_skill_registered(files: list, errors: list):
    agents = REPO_ROOT / "AGENTS.md"
    agents_text = agents.read_text() if agents.exists() else ""
    for status, path in files:
        if status != "A" or not path.endswith("/SKILL.md") or "/skills/" not in path:
            continue
        skill_name = Path(path).parent.name
        if skill_name not in agents_text:
            errors.append(
                f"{path}: new skill '{skill_name}' is not registered in AGENTS.md "
                f"(add it to the Skills list)."
            )


def check_no_stub_markers(files: list, errors: list):
    guard_name = Path(__file__).name
    for status, path in files:
        if status not in ("A", "M"):
            continue
        p = Path(path)
        if p.suffix not in CODE_SUFFIXES:
            continue
        if path.startswith("tests/") or p.name == guard_name:
            continue
        full = REPO_ROOT / path
        if not full.exists():
            continue
        for i, line in enumerate(full.read_text().splitlines(), 1):
            low = line.lower()
            for marker in STUB_MARKERS:
                if marker in low:
                    errors.append(
                        f"{path}:{i}: stub marker '{marker}' in shipped code — "
                        f"finish it or open a follow-up issue and remove the marker."
                    )


def main():
    parser = argparse.ArgumentParser(description="opskit definition-of-done guard")
    parser.add_argument(
        "--cached", action="store_true", help="check staged changes (default)"
    )
    parser.add_argument(
        "range", nargs="?", help="git range, e.g. origin/main...HEAD"
    )
    args = parser.parse_args()
    target = args.range if (args.range and not args.cached) else "--cached"

    print("=== definition-of-done guard ===")

    if os.environ.get("ALLOW_DOD_SKIP") == "1":
        print("WARNING: ALLOW_DOD_SKIP=1 set — skipping definition-of-done checks.")
        return 0

    files = changed_files(target)
    if not files:
        print("No added/modified files to check.")
        return 0

    errors: list = []
    check_new_tool_has_test(files, errors)
    check_new_skill_registered(files, errors)
    check_no_stub_markers(files, errors)

    if errors:
        print("ERROR: definition-of-done checks failed:\n", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "\nSee .opencode/rules/definition-of-done.md. "
            "Override (discouraged): ALLOW_DOD_SKIP=1",
            file=sys.stderr,
        )
        return 1

    print(f"All definition-of-done checks passed ({len(files)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
