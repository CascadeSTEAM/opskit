#!/usr/bin/env python3
"""check-mcp-wiring.py — flag MCP entries wired to copies outside this repo.

Every copy-drift incident of 2026-08 had the same shape: a sibling checkout's
copy kept executing long after this repo's version became canonical, and
nothing could tell it was stale (issues #80/#81, #143, #146). This reporter
makes that staleness LOUD: it reads the local opencode config and flags any
MCP server this repo ships that is wired to run from somewhere else.

Verdicts per configured MCP entry naming a shipped server:
  ERROR — command resolves through a filesystem path outside this repo:
          a sibling checkout's copy is live. Exit 1.
  WARN  — command uses a package runner (uvx/npx/pipx) instead of the
          in-repo server: a duplicate implementation exists. Exit 0.

Entries for servers this repo does not ship (other projects' MCP servers,
external services) are none of our business and never flagged.

Usage:
  bin/check-mcp-wiring.py [--config PATH]

Config path default: ~/.config/opencode/opencode.json
Repo root: OPSKIT_ROOT env var > this script's parent directory. (OPSKIT_ROOT
is the caller-overridable DATA root elsewhere; here the check is about THIS
checkout, so the script's own location is the honest default.)
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_REPO = Path(__file__).resolve().parent.parent
PACKAGE_RUNNERS = ('uvx', 'npx', 'pipx')


def shipped_servers(repo: Path) -> set[str]:
    """Server names this repo can launch — derived from bin/mcp-run.sh --list's
    source of truth: mcp/*-mcp-server.py plus generated external configs."""
    names = {
        p.name.removesuffix('-mcp-server.py')
        for p in (repo / 'mcp').glob('*-mcp-server.py')
    }
    # mikromcp is launched via generated config rather than an in-repo *.py
    if (repo / 'bin' / 'gen-mikromcp-config.py').exists():
        names.add('mikromcp')
    return names


def command_text(entry) -> str:
    """opencode accepts a string or argv list for an MCP server command."""
    cmd = entry.get('command') if isinstance(entry, dict) else None
    if isinstance(cmd, list):
        return ' '.join(str(c) for c in cmd)
    return str(cmd or '')


def check(config: dict, repo: Path) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings)."""
    servers = shipped_servers(repo)
    errors, warnings = [], []

    for name, entry in (config.get('mcp') or {}).items():
        cmd = command_text(entry)
        if not cmd:
            continue
        hit = next(
            (s for s in servers
             if s in name or s in cmd),
            None)
        if hit is None:
            continue
        if str(repo) in cmd:
            continue  # wired to this checkout — correct
        first = cmd.split()[0] if cmd.split() else ''
        if os.path.basename(first) in PACKAGE_RUNNERS:
            warnings.append(
                f"{name}: shipped server '{hit}' runs via package runner "
                f"({first}) — duplicate implementation of {repo}/mcp; "
                f"consider bin/mcp-run.sh {hit}")
        elif '/' in cmd:
            errors.append(
                f"{name}: shipped server '{hit}' executes from OUTSIDE this "
                f"repo: {cmd} — a sibling checkout's copy is live "
                f"(fix: {repo}/bin/mcp-run.sh {hit})")
        else:
            warnings.append(
                f"{name}: shipped server '{hit}' wired as '{cmd}' — "
                f"not this repo's launcher; verify intentional")
    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--config',
                    default=os.path.expanduser('~/.config/opencode/opencode.json'))
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"NOTE: no opencode config at {cfg_path} — nothing to check.")
        return 0
    try:
        config = json.loads(cfg_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: {cfg_path} is not valid JSON: {e}")
        return 1

    repo = Path(os.environ.get('OPSKIT_ROOT', SCRIPT_REPO)).resolve()
    errors, warnings = check(config, repo)

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        print(f"\n{len(errors)} sibling-checkout execution(s) — "
              "this is the drift bin/mcp-run.sh exists to end (#146).")
        return 1
    if not warnings:
        print("MCP wiring clean: every shipped server runs from this repo.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
