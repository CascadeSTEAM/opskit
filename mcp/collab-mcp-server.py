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


def _command_names() -> set[str]:
    """Return set of slash command names from .opencode/command/*.md files."""
    cmd_dir = REPO_ROOT / ".opencode" / "command"
    if not cmd_dir.is_dir():
        return set()
    return {p.stem for p in cmd_dir.iterdir() if p.is_file() and p.suffix == ".md"}


def _read_frontmatter(text: str) -> tuple[dict, str]:
    """Return (fm_dict, body) for a doc with '---' YAML frontmatter.

    Uses yaml.safe_load first; falls back to a line-parser that handles
    long values containing colons (which confuse the YAML parser).
    """
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    raw = m.group(1)
    try:
        import yaml
        fm = yaml.safe_load(raw) or {}
    except Exception:
        # Fallback: parse "key: value" lines, handling colons in values.
        # YAML spec: key, then ': ', then value to end-of-line.
        fm: dict[str, str] = {}
        for line in raw.splitlines():
            colon_idx = line.find(": ")
            if colon_idx > 0:
                key = line[:colon_idx].strip()
                value = line[colon_idx + 2:]
                fm[key] = value
    return fm, m.group(2)


def _command_for_skill(name: str, desc: str, triggers: str) -> str:
    """Generate a .opencode/command/<name>.md file from skill metadata."""
    use_triggers = f"/{name}, {triggers}" if triggers else f"/{name}, {name}"
    # Build unique trigger list, preserving order
    parts = [t.strip() for t in use_triggers.split(",")]
    seen = set()
    unique = []
    for p in parts:
        lower = p.lower()
        if lower not in seen:
            seen.add(lower)
            unique.append(p)
    use_line = ", ".join(unique)
    description_line = desc if f"/{name}" in desc else f"{desc}. Use for: {use_line}."
    return (
        f"---\n"
        f"description: {description_line}\n"
        f"---\n"
        f"\n"
        f"Call the skill tool to load the \"{name}\" skill, then follow its "
        f"instructions exactly.\n"
        f"\n"
        f"$ARGUMENTS\n"
    )


@mcp.tool()
def collab_skill_command_drift() -> str:
    """Compare skills against .opencode/command/*.md files.

    Opencode slash commands are defined in .opencode/command/<name>.md — the file
    stem is the command name (e.g. cleanup.md → /cleanup). Skills live in
    .opencode/skills/<name>/SKILL.md and are a separate discovery mechanism. A skill
    without a corresponding command file is not a bug (skills can be auto-triggered
    via the triggers: frontmatter), but any skill whose triggers: include a
    /command pattern should have a command file — and this tool flags skills that
    are missing from the command directory for manual review.
    """
    skill_dir = REPO_ROOT / ".opencode" / "skills"
    cmd_dir = REPO_ROOT / ".opencode" / "command"

    if not skill_dir.is_dir():
        return json.dumps({"error": f"{skill_dir} does not exist"}, indent=2)

    cmd_names = _command_names()

    # Gather skill metadata
    skills: list[dict] = []
    for sd in sorted(skill_dir.iterdir()):
        if not (sd / "SKILL.md").is_file():
            continue
        fm, body = _read_frontmatter((sd / "SKILL.md").read_text())
        desc = str(fm.get("description") or "").strip()
        triggers = str(fm.get("triggers") or "").strip()
        has_slash_trigger = bool(re.search(r"/[a-z]", triggers))
        skills.append({
            "name": sd.name,
            "has_slash_trigger": has_slash_trigger,
            "triggers": triggers,
            "description": desc,
        })

    # Check which skills need command files (those with slash triggers)
    needs_command = [
        s for s in skills
        if s["name"] not in cmd_names and s["has_slash_trigger"]
    ]

    # Report all skills vs commands (not just slash-trigger ones)
    skill_names = {s["name"] for s in skills}

    return json.dumps({
        "command_files": sorted(cmd_names),
        "skills_without_command": sorted(skill_names - cmd_names),
        "skills_needing_command_file": [
            {"name": s["name"], "triggers": s["triggers"]}
            for s in needs_command
        ],
        "total_skills": len(skills),
        "total_commands": len(cmd_names),
        "ok": len(needs_command) == 0,
        "note": ("Skills auto-trigger via triggers: frontmatter — they do not "
                 "need a command file to be discovered. A command file is "
                 "only needed when the operator wants /command. This tool flags "
                 "skills whose triggers include / patterns but lack a command "
                 "file so they can be manually reviewed and created."),
    }, indent=2)


@mcp.tool()
def collab_create_commands(skills: list[str]) -> str:
    """Create .opencode/command/<name>.md files for the named skills.

    Takes a list of skill names (e.g. ["grind", "cleanup"]). Uses the skill's
    description and triggers: frontmatter to generate the command file.
    Does not overwrite existing command files.
    """
    skill_dir = REPO_ROOT / ".opencode" / "skills"
    cmd_dir = REPO_ROOT / ".opencode" / "command"
    cmd_dir.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    import yaml

    for name in sorted(skills):
        skill_md = skill_dir / name / "SKILL.md"
        cmd_file = cmd_dir / f"{name}.md"

        if cmd_file.exists():
            skipped.append(name)
            continue

        if not skill_md.is_file():
            errors.append(f"{name}: SKILL.md not found")
            continue

        text = skill_md.read_text()
        fm, _ = _read_frontmatter(text)
        desc = str(fm.get("description") or "").strip()
        triggers = str(fm.get("triggers") or "").strip()

        content = _command_for_skill(name, desc, triggers)
        cmd_file.write_text(content)
        created.append(name)

    return json.dumps({
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "note": ("Command files written to .opencode/command/. Restart the "
                 "opencode session for new slash commands to be discovered."),
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

    # Skill → command drift: skills with slash triggers but no .opencode/command/<name>.md
    drift = json.loads(collab_skill_command_drift())
    for entry in drift["skills_needing_command_file"]:
        proposals.append({
            "priority": "medium",
            "why": ("a slash command that does not work wastes the session — the skill "
                   "is auto-discovered but /command does not resolve"),
            "change": (f"skill `{entry['name']}` has slash triggers ({entry['triggers']}) "
                       f"but no `.opencode/command/{entry['name']}.md` — create it or remove "
                       f"the slash triggers"),
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


if __name__ == "__main__" and "--test" in sys.argv:
    # Standalone test mode (not an MCP tool invocation)
    print(collab_skill_command_drift())
    print()
    print(collab_propose_improvements())
