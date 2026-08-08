#!/usr/bin/env python3
"""MCP server for the AI-collaboration layer — the agent's own operating surface.

opskit #136. This repo has two layers. The *product* layer is what OpsKit does to
environments, and Development Principle #2 arbitrates its vehicles. The
*collaboration* layer is the operator, the agent, and the OpsKit CLI between them:
AGENTS.md, CLAUDE.md, .opencode/skills/, agents/, harness wiring. Principle #2 does not govern
it, and until now nothing improved it either — there is a self-improvement ladder for
the product and nothing at all for the surface every session depends on.

AGENTS.md is the highest-leverage file in the repo: every session reads it, so drift
there degrades every session. And it drifts. Found in one day, without looking: a skill
list matching neither skill tree; a skill instructing `npm run session:end` in a repo
with no package.json; another naming a script that does not exist; a third claiming a
git hook that has never existed. Every one of those is a checkable claim, and nothing
checked any of them.

VERIFY IS AUTOMATED. REWRITING IS NOT.
These files are the control surface for agent behaviour. An automated edit can silently
weaken a hard rule, and no test catches a rule that has merely been softened — the same
shape as setting a flag to make a check pass. So `collab_propose_improvements` returns
proposals and this server never writes AGENTS.md or CLAUDE.md. A human disposes.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - surfaced by mcp-run.sh --check
    print("ERROR: the `mcp` package is not importable — run: make deps", file=sys.stderr)
    raise

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT", Path(__file__).resolve().parent.parent))

mcp = FastMCP("opskit-collab")

# Docs that describe the collaboration surface and can therefore be wrong about it.
GOVERNING_DOCS = ("AGENTS.md", "CLAUDE.md")

# Inline-code spans that look like a repo path. Anchored on the known top-level
# directories so ordinary prose in backticks is not mistaken for a file.
PATH_IN_BACKTICKS = re.compile(
    r"`((?:bin|mcp|ansible|schemas|docs|skills|agents|tests|\.githooks|\.opencode)/[^`\s]+)`"
)


def _read(name: str) -> str:
    path = REPO_ROOT / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _referenced_paths(text: str) -> set[str]:
    found = set()
    for raw in PATH_IN_BACKTICKS.findall(text):
        # Strip trailing punctuation and glob-ish placeholders that are not literal.
        cleaned = raw.rstrip(".,;:)")
        if any(ch in cleaned for ch in "<>*"):
            continue
        found.add(cleaned)
    return found


def _skill_names() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for tree in ("skills", ".opencode/skills"):
        d = REPO_ROOT / tree
        if d.is_dir():
            out[tree] = {p.name for p in d.iterdir()
                         if (p / "SKILL.md").is_file()}
    return out


def _listed_skills(text: str) -> set[str]:
    """Backticked names in the Skills section of AGENTS.md.

    Anchored on the heading rather than on punctuation. An earlier version keyed off
    "a line with at least three pipes", which is a guess about formatting rather than
    about meaning — it broke the moment the list was written with two separators, and
    a heuristic that depends on how many pipes someone typed will keep breaking.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#") and "skill" in line.lower():
            names: set[str] = set()
            for follower in lines[i + 1:i + 6]:
                if follower.startswith("#"):
                    break
                if "/" in follower:
                    continue          # a path, not a skill name
                names |= set(re.findall(r"`([a-z][a-z0-9-]*)`", follower))
            if names:
                return names
    return set()


def _bin_scripts() -> set[str]:
    d = REPO_ROOT / "bin"
    if not d.is_dir():
        return set()
    out = set()
    for p in d.iterdir():
        if p.is_file() and not p.name.startswith((".", "_")) and p.name != "adapters":
            out.add(f"bin/{p.name}")
    return out


@mcp.tool()
def collab_verify_docs() -> str:
    """Check that every path AGENTS.md and CLAUDE.md name actually exists.

    These documents are read at the start of every session, so a reference to a
    file that does not exist sends an agent down a path that cannot work — which
    has already happened. Reports; changes nothing.
    """
    findings: list[dict] = []
    checked = 0

    for doc in GOVERNING_DOCS:
        text = _read(doc)
        if not text:
            findings.append({"doc": doc, "kind": "missing-document",
                             "detail": f"{doc} does not exist"})
            continue
        for ref in sorted(_referenced_paths(text)):
            checked += 1
            if not (REPO_ROOT / ref).exists():
                findings.append({"doc": doc, "kind": "broken-reference",
                                 "detail": f"`{ref}` is named but does not exist"})

    return json.dumps({
        "references_checked": checked,
        "findings": findings,
        "ok": not findings,
        "note": ("Reports only. These documents are the control surface for agent "
                 "behaviour and this server never edits them."),
    }, indent=2)


@mcp.tool()
def collab_skill_drift() -> str:
    """Compare the skills AGENTS.md advertises against the skills that exist.

    A skill listed but absent sends an agent looking for guidance that is not there;
    a skill present but unlisted is invisible and never gets used. Both are silent.
    """
    text = _read("AGENTS.md")
    listed = _listed_skills(text)
    trees = _skill_names()
    on_disk: set[str] = set()
    for names in trees.values():
        on_disk |= names

    return json.dumps({
        "listed_in_agents_md": sorted(listed),
        "present_on_disk": {tree: sorted(names) for tree, names in trees.items()},
        "listed_but_absent": sorted(listed - on_disk),
        "present_but_unlisted": sorted(on_disk - listed),
        "in_both_trees": sorted(set.intersection(*trees.values())) if len(trees) > 1 else [],
        "ok": not (listed - on_disk) and not (on_disk - listed),
    }, indent=2)


@mcp.tool()
def collab_tool_drift() -> str:
    """Compare the scripts AGENTS.md documents against what is in bin/.

    Every tool built needs a hand-added row in the tool table today, and nothing
    notices a forgotten one — an undocumented tool is one no agent will reach for.
    """
    text = _read("AGENTS.md")
    documented = {p for p in _referenced_paths(text) if p.startswith("bin/")}
    present = _bin_scripts()

    return json.dumps({
        "documented": sorted(documented),
        "present_in_bin": sorted(present),
        "documented_but_absent": sorted(documented - present),
        "present_but_undocumented": sorted(present - documented),
        "ok": not (documented - present),
        "note": ("An undocumented script is not necessarily wrong — some are internal. "
                 "Absent-but-documented always is."),
    }, indent=2)


@mcp.tool()
def collab_propose_improvements() -> str:
    """Propose changes to the governing docs. Returns text; writes nothing, ever.

    Deliberately advisory. Verifying these files can be automated freely; rewriting
    them cannot, because an automated edit can silently weaken a hard rule and no test
    catches a rule that has merely been softened. The operator decides.
    """
    proposals: list[dict] = []

    verify = json.loads(collab_verify_docs())
    for f in verify["findings"]:
        proposals.append({
            "priority": "high",
            "why": "a reference that does not resolve sends an agent down a dead path",
            "change": f"{f['doc']}: {f['detail']}",
        })

    skills = json.loads(collab_skill_drift())
    for name in skills["listed_but_absent"]:
        proposals.append({
            "priority": "high",
            "why": "an agent told to load this finds nothing",
            "change": f"AGENTS.md advertises skill `{name}` which does not exist",
        })
    for name in skills["present_but_unlisted"]:
        proposals.append({
            "priority": "medium",
            "why": "an unlisted skill is invisible and never gets used",
            "change": f"skill `{name}` exists but AGENTS.md does not list it",
        })

    tools = json.loads(collab_tool_drift())
    for path in tools["documented_but_absent"]:
        proposals.append({
            "priority": "high",
            "why": "documented tooling that is not there",
            "change": f"AGENTS.md documents `{path}` which does not exist",
        })

    text = _read("AGENTS.md")
    if text and len(text.splitlines()) > 300:
        proposals.append({
            "priority": "low",
            "why": ("length is read in full every session; past a point the cost is "
                    "paid continuously and the tail stops being read"),
            "change": f"AGENTS.md is {len(text.splitlines())} lines — consider "
                      f"extracting reference material and leaving the rules",
        })

    return json.dumps({
        "proposals": proposals,
        "count": len(proposals),
        "note": ("PROPOSALS ONLY — nothing was written. These files are the control "
                 "surface for agent behaviour; an automated edit can weaken a hard "
                 "rule invisibly. A human decides which of these to apply."),
    }, indent=2)


if __name__ == "__main__":
    if "--test" in sys.argv:
        print(collab_verify_docs())
        print(collab_skill_drift())
        print(collab_tool_drift())
        print(collab_propose_improvements())
    else:
        mcp.run(transport="stdio")
