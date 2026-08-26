#!/usr/bin/env python3
"""idea-cmd.py — interactive capture + dedupe CLI for the idea ledger.

Complements bin/idea.py (raw ledger I/O) with:
  - capture: interactive prompt, returns JSON (no ledger write)
  - dedupe: search ledger + GH issues, return matches
  - enrich: update desire level and notes on an existing row

Used by the idea-cmd skill for the /idea conversation flow.
The skill does the judgment; this script does the plumbing.

Usage:
  bin/idea-cmd.py capture          # interactive capture, prints JSON to stdout
  bin/idea-cmd.py dedupe <title>   # search ledger + GH for duplicates
  bin/idea-cmd.py enrich --row N --desire D [--notes N]
  bin/idea-cmd.py enrich --title T --desire D [--notes N]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Resolve the real repo root (handles worktrees).
# OPSKIT_ROOT env var allows tests to override.
def _resolve_repo_root() -> Path:
    if "OPSKIT_ROOT" in os.environ:
        return Path(os.environ["OPSKIT_ROOT"])
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return Path(__file__).resolve().parents[1]

REPO_ROOT = _resolve_repo_root()

# Import shared helpers from bin/idea.py to stay in sync
# (same approach bin/opskit uses — sys.path insert + import)
sys.path.insert(0, str(REPO_ROOT / "bin"))
import idea as _idea_module  # noqa: E402 — loaded after REPO_ROOT is set


def _get_repo_root(ledger_path: Optional[Path] = None) -> Path:
    """Resolve repo root from ledger path or REPO_ROOT."""
    if ledger_path:
        return ledger_path.parent.parent  # ledger is <repo>/docs/ideas.md
    return REPO_ROOT


def _git_root_cwd() -> Optional[Path]:
    """Return the root of the git repo at cwd, or None."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _git_remote_url() -> Optional[str]:
    """Return the origin remote URL, or None."""
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def _gh_issue_search(title: str) -> list[dict]:
    """Search GitHub for potentially related issues (best-effort)."""
    results: list[dict] = []
    try:
        out = subprocess.run(
            ["gh", "issue", "list", "--state", "all", "--search", title,
             "--limit", "5", "--json", "number,title,state,url"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(out.stdout)
        for issue in data:
            results.append({
                "type": "gh",
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "url": issue["url"],
            })
    except (subprocess.CalledProcessError, FileNotFoundError, OSError, json.JSONDecodeError):
        pass  # gh unreachable or no results
    return results


def _ledger_search(ledger_path: Path, title: str) -> list[tuple[int, dict]]:
    """Search the ledger for matching rows (substring, case-insensitive)."""
    results: list[tuple[int, dict]] = []
    if not ledger_path.exists():
        return results

    ledger = _idea_module.load_ledger(ledger_path)
    title_lower = title.lower()
    # numbered() returns list of (row_num, Idea) tuples — iterate directly
    for row_num, idea in _idea_module.numbered(ledger):
        idea_dict = {
            "date": idea.date,
            "desire": idea.desire,
            "title": idea.title,
            "desc": idea.desc,
            "status": idea.status,
            "gh": idea.gh,
        }
        haystack = f"{idea.title} {idea.desc}".lower()
        if title_lower in haystack or title_lower.split()[-1] in haystack:
            results.append((row_num, idea_dict))
    return results


# --- subcommands -----------------------------------------------------------


def cmd_capture(args: argparse.Namespace) -> None:
    """Interactive capture: prompt for title and description, print JSON."""
    title = args.title or _prompt("Title: ")
    if not title.strip():
        print("ERROR: title is required", file=sys.stderr)
        sys.exit(1)

    desc = args.desc or _prompt(f"Description (press enter to skip, or type the idea):\n  ")

    result = {
        "title": title.strip(),
        "description": desc.strip() if desc else "",
    }
    print(json.dumps(result, ensure_ascii=False))


def cmd_dedupe(args: argparse.Namespace) -> None:
    """Search ledger + GH issues for potential duplicates."""
    title = " ".join(args.title).strip()
    if not title:
        print(json.dumps({"error": "title argument required"}))
        sys.exit(1)

    ledger_path = Path(args.file) if args.file else None
    repo_root = _get_repo_root(ledger_path)

    # Determine ledger path
    if ledger_path and ledger_path.exists():
        target_ledger = ledger_path
    else:
        target_ledger = repo_root / "docs" / "ideas.md"

    results: list[dict] = []

    # Search ledger
    ledger_matches = _ledger_search(target_ledger, title)
    for idx, idea in ledger_matches:
        results.append({
            "type": "ledger",
            "row": idx,
            "title": idea["title"],
            "status": idea["status"],
            "desire": idea["desire"],
            "gh": idea["gh"],
        })

    # Search GH issues
    if args.gh:
        gh_matches = _gh_issue_search(title)
        for issue in gh_matches:
            results.append(issue)

    output = {
        "query": title,
        "matches": results,
        "count": len(results),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_enrich(args: argparse.Namespace) -> None:
    """Update an existing ledger row's desire level and/or notes."""
    ledger_path = Path(args.file) if args.file else None
    if ledger_path:
        target_ledger = ledger_path
    else:
        target_ledger = _get_repo_root() / "docs" / "ideas.md"

    ledger = _idea_module.load_ledger(target_ledger)

    if args.row is not None:
        if args.row < 1 or args.row > len(ledger.rows):
            raise SystemExit(f"row {args.row} out of range (1..{len(ledger.rows)})")
        idx = args.row - 1
    else:
        matches = [i for i, idea in enumerate(ledger.rows) if idea.title == args.title]
        if not matches:
            raise SystemExit(f"no row found with title exactly: {args.title!r}")
        if len(matches) > 1:
            raise SystemExit(
                f"ambiguous: {len(matches)} rows have title {args.title!r}; use --row instead"
            )
        idx = matches[0]

    row = ledger.rows[idx]
    updated = False

    if args.desire is not None:
        row.desire = str(args.desire)
        updated = True

    if args.notes:
        existing = row.desc if row.desc else ""
        row.desc = _idea_module.flatten(f"{existing}; {args.notes}") if existing else args.notes
        updated = True

    if args.status:
        row.status = args.status
        updated = True

    if args.gh is not None:
        row.gh = str(args.gh)
        updated = True

    if not updated:
        print("no changes to apply (use --desire, --notes, --status, or --gh)")
        return

    ledger.write()
    print(f"row {idx + 1} updated: {row.title} (desire={row.desire}, status={row.status})")


# --- helpers ----------------------------------------------------------------


def _prompt(label: str) -> str:
    """Print a label and read a line from stdin (non-interactive safe)."""
    sys.stdout.write(label)
    sys.stdout.flush()
    try:
        return input()
    except EOFError:
        return ""


# --- CLI wiring --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file", type=Path, default=None,
        help="path to the ideas ledger (default: docs/ideas.md at the repo root)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    # capture
    cap_p = sub.add_parser("capture", help="interactive capture, prints JSON to stdout")
    cap_p.add_argument("--title", default=None, help="title (prompts if omitted)")
    cap_p.add_argument("--desc", default=None, help="description (prompts if omitted)")
    cap_p.set_defaults(func=cmd_capture)

    # dedupe
    ded_p = sub.add_parser("dedupe", help="search ledger + GH for duplicates")
    ded_p.add_argument("title", nargs="+", help="title to deduplicate against")
    ded_p.add_argument("--gh", action="store_true", help="also search GH issues")
    ded_p.set_defaults(func=cmd_dedupe)

    # enrich
    enr_p = sub.add_parser("enrich", help="update desire/notes on an existing row")
    enr_target = enr_p.add_mutually_exclusive_group(required=True)
    enr_target.add_argument("--row", type=int, help="1-based row number")
    enr_target.add_argument("--title", help="exact title match")
    enr_p.add_argument("--desire", type=int, choices=range(1, 6), help="importance 1-5")
    enr_p.add_argument("--notes", help="additional notes to append")
    enr_p.add_argument("--status", default=None, help="set status (new/accepted/declined)")
    enr_p.add_argument("--gh", type=int, default=None, help="GH issue number")
    enr_p.set_defaults(func=cmd_enrich)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
