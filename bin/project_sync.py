#!/usr/bin/env python3
"""bin/project-sync.py — manage OpsKit member repos (clone/pull/symlink + mount).

Members are declared in .project-remotes (one per line). Each member declares
how it should be obtained:
  - sync=symlink: an absolute local path is provided, create a symlink into
    projects/<name>/
  - sync=clone: a git URL is provided, clone into $OPSKIT_MEMBERS_DIR/<name>/

Members live in $OPSKIT_MEMBERS_DIR (default: ~/Projects/) — external to the
OpsKit checkout so concurrent sessions never block on git ops.
projects/<name>/ inside OpsKit is a symlink to the member.

Usage:
    bin/project-sync.py status [--json]          # show mount state per member
    bin/project-sync.py sync                     # clone/pull + create symlinks
    bin/project-sync.py pull                     # pull updates for clone members
    bin/project-sync.py mount [--dry-run]        # validate + render agents/skills; REPORTS stale
    bin/project-sync.py sync-mount               # sync + mount in one step (never deletes)
    bin/project-sync.py prune [--force] [--dry-run]  # report (or with --force remove) stale member renders

Exit codes: `mount` / `sync-mount` exit 1 when there are errors, conflicts or (sync-mount)
sync failures; skipped items and stale renders exit 0. Other commands exit 0 on partial success.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("project-sync: PyYAML is required — `pip install pyyaml`.\n")
    sys.exit(1)

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = _SCRIPT_DIR.parent

_REMOTES = REPO_ROOT / ".project-remotes"
_PROJECTS = REPO_ROOT / "projects"
_EXAMPLE = _PROJECTS / "example"

# Mutable references so tests can swap them out.
# (Assigned once at module load; tests may overwrite the attrs.)
# Deliberately empty — the three above are the real assignments.

# External directory where member repos actually live (git clone target or
# symlink source). Default mirrors where opsit itself lives.
DEFAULT_MEMBERS_DIR = Path.home() / "Projects"
MEMBERS_DIR_ENV = "OPSKIT_MEMBERS_DIR"


def _members_dir() -> Path:
    """Resolve member base directory from env or default."""
    raw = os.environ.get(MEMBERS_DIR_ENV, "")
    if raw:
        return Path(raw)
    return DEFAULT_MEMBERS_DIR


def _log(msg: str, **kwargs: Any) -> None:
    """Print human-readable output to stderr."""
    prefix = f"[project-sync] "
    print(f"{prefix}{msg}", file=sys.stderr, **kwargs)


def _emit(data: dict) -> None:
    """Print JSON result to stdout."""
    print(json.dumps(data, indent=2, default=str))


# ── .project-remotes parsing ──────────────────────────────────────────────────


def parse_remotes(path: Path) -> list[dict]:
    """Parse .project-remotes, return list of member dicts."""
    if not path.is_file():
        return []

    members: list[dict] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            _log(f"WARNING: {path}:{lineno}: skipping malformed line: {raw}")
            continue

        name = parts[0]
        path_or_url = parts[1]
        pin = parts[2] if len(parts) > 2 else None

        members.append({
            "name": name,
            "path": path_or_url,
            "pin": pin,
            "line": lineno,
            "raw": line,
        })

    return members


# ── Member state helpers ──────────────────────────────────────────────────────


def _member_pack_path(member_root: Path) -> Path:
    """Return the path to a member's pack.yml."""
    return member_root / ".opskit" / "pack.yml"


def _load_pack(path: Path) -> dict | None:
    """Load and parse pack.yml, return None if missing."""
    if not path.is_file():
        return None
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _member_local_dir(member: dict) -> Path:
    """Path where a member repo lives on disk.

    Resolves the source path from .project-remotes:
    - Absolute paths → used as-is (after ~ expansion)
    - Relative paths → resolved relative to REPO_ROOT
    """
    src = os.path.expanduser(member["path"])
    p = Path(src)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def _member_mount_link(projects_dir: Path, name: str) -> Path:
    """Path of the symlink inside projects/<name>/."""
    return projects_dir / name


def _is_mounted(member: dict, pack: dict | None) -> bool:
    """Check if a member is currently mounted (local dir + mount link + valid pack)."""
    local = _member_local_dir(member)
    if not local.is_dir():
        return False
    # Skip the committed example/ reference — it lives inside projects/
    # but is NOT a mounted member.
    if local == _EXAMPLE:
        return False
    if pack is None or "name" not in pack:
        return False

    mount_link = _member_mount_link(_PROJECTS, member["name"])
    # For both clone and symlink members, a mount link must exist in projects/
    return mount_link.exists() or mount_link.is_symlink()


def _is_stale_member(member: dict, remotes: list[dict]) -> bool:
    """Check if a member has no entry in .project-remotes (stale)."""
    return not any(r["name"] == member["name"] for r in remotes)


# ── Git helpers ───────────────────────────────────────────────────────────────


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command, return result."""
    return subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _git_clone(url: str, target: Path, pin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Clone a git repo, optionally pinning to a ref."""
    cmd = ["clone", "--depth", "1", url, str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(target.parent))
    if proc.returncode == 0 and pin:
        # Checkout the pin
        checkout = _git("checkout", pin, cwd=target)
        if checkout.returncode != 0:
            # Try fetching + checking out if clone was shallow
            _git("fetch", "origin", pin, cwd=target)
            _git("checkout", pin, cwd=target)
    return proc


def _git_pull(target: Path) -> subprocess.CompletedProcess[str]:
    """Pull latest in a cloned repo."""
    return _git("pull", "--ff-only", cwd=target)


# ── Status ────────────────────────────────────────────────────────────────────


def cmd_status() -> dict:
    """Show mount state for all members in .project-remotes."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {
            "members": [],
            "summary": {"total": 0, "mounted": 0, "missing": 0, "stale": 0},
            "note": "No members declared in .project-remotes.",
        }

    members_dir = _members_dir()
    results: list[dict] = []
    mounted = 0
    skipped = 0
    missing = 0

    for remote in remotes:
        local = _member_local_dir(remote)
        pack = _load_pack(_member_pack_path(local))

        # Skip committed example/ reference
        if local == _EXAMPLE:
            results.append({
                "name": remote["name"],
                "source": remote["path"],
                "sync": pack.get("sync", "unknown") if pack else "unknown",
                "state": "skipped",
            })
            skipped += 1
            continue

        if _is_mounted(remote, pack):
            state = "mounted"
            mounted += 1
        else:
            state = "missing"
            missing += 1

        results.append({
            "name": remote["name"],
            "source": remote["path"],
            "sync": pack.get("sync", "unknown") if pack else "unknown",
            "state": state,
        })

    return {
        "members": results,
        "summary": {
            "total": len(results),
            "mounted": mounted,
            "skipped": skipped,
            "missing": missing,
        },
    }


# ── Sync ──────────────────────────────────────────────────────────────────────


def cmd_sync() -> dict:
    """Clone/pull members and create/update symlinks."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {"synced": [], "note": "No members declared in .project-remotes."}

    members_dir = _members_dir()
    members_dir.mkdir(parents=True, exist_ok=True)

    synced: list[dict] = []
    errors: list[dict] = []

    for remote in remotes:
        name = remote["name"]
        path_or_url = remote["path"]
        pin = remote["pin"]
        local = _member_local_dir(remote)
        mount_link = _member_mount_link(_PROJECTS, name)

        # Skip committed example/ reference — it lives in projects/ but is not a mounted member.
        if local == _EXAMPLE:
            synced.append({"name": name, "status": "skipped", "reason": "committed reference (projects/example/)"})
            continue

        try:
            # Determine sync mode from pack.yml
            pack = _load_pack(_member_pack_path(local))
            if pack is None:
                # No pack.yml yet — assume symlink mode if path exists,
                # clone otherwise.  But a bare local path that doesn't exist
                # and has no "://" is almost certainly a broken symlink source,
                # not a git URL — report it cleanly.
                is_clone = not local.is_dir()
                if is_clone and "://" not in path_or_url:
                    synced.append({"name": name, "status": "missing_source", "source": path_or_url})
                    continue
            else:
                is_clone = pack.get("sync") == "clone"

            if is_clone:
                # Clone or pull
                # For clone, local = $OPSKIT_MEMBERS_DIR/<name>/
                clone_target = local
                if not clone_target.is_dir():
                    proc = _git_clone(path_or_url, clone_target, pin)
                    if proc.returncode != 0:
                        errors.append({"name": name, "error": proc.stderr.strip()[:200]})
                        synced.append({"name": name, "status": "failed"})
                        continue
                else:
                    proc = _git_pull(clone_target)
                    if proc.returncode != 0:
                        errors.append({"name": name, "error": proc.stderr.strip()[:200]})
                        synced.append({"name": name, "status": "pull_failed"})
                        continue

                synced.append({"name": name, "status": "cloned" if proc.returncode == 0 else "up_to_date"})

                # Create mount symlink
                if mount_link.exists() or mount_link.is_symlink():
                    mount_link.unlink()
                _PROJECTS.mkdir(parents=True, exist_ok=True)
                mount_link.symlink_to(clone_target)
                synced[-1]["mount"] = "symlinked"
            else:
                # Symlink mode — verify local path, create/update mount link
                source = local.resolve()
                if not source.is_dir():
                    errors.append({"name": name, "error": f"symlink source not found: {source}"})
                    synced.append({"name": name, "status": "missing_source"})
                    continue

                if mount_link.exists() or mount_link.is_symlink():
                    # Check if symlink already points to the right target
                    try:
                        if mount_link.resolve() == source:
                            synced.append({"name": name, "status": "up_to_date", "source": str(source)})
                            continue
                    except (OSError, ValueError):
                        pass

                    mount_link.unlink()

                _PROJECTS.mkdir(parents=True, exist_ok=True)
                mount_link.symlink_to(source)
                synced.append({"name": name, "status": "symlinked", "source": str(source)})

        except Exception as e:
            errors.append({"name": name, "error": str(e)[:200]})
            synced.append({"name": name, "status": "error", "error": str(e)[:200]})

    return {
        "synced": synced,
        "errors": errors,
        "members_dir": str(members_dir),
        "projects_dir": str(_PROJECTS),
        "summary": {
            "total": len(remotes),
            "synced": len(synced) - len(errors),
            "failed": len(errors),
        },
    }


# ── Pull ──────────────────────────────────────────────────────────────────────


def cmd_pull() -> dict:
    """Pull updates for all clone-mode members."""
    remotes = parse_remotes(_REMOTES)
    if not remotes:
        return {"pulled": [], "note": "No members declared."}

    members_dir = _members_dir()
    pulled: list[dict] = []
    errors: list[dict] = []

    for remote in remotes:
        name = remote["name"]
        local = _member_local_dir(remote)

        pack = _load_pack(_member_pack_path(local))
        if pack is None or pack.get("sync") != "clone":
            pulled.append({"name": name, "status": "skipped", "reason": "not clone mode"})
            continue

        if not local.is_dir():
            pulled.append({"name": name, "status": "skipped", "reason": "not cloned"})
            continue

        proc = _git_pull(local)
        if proc.returncode == 0:
            pulled.append({"name": name, "status": "pulled"})
        else:
            errors.append({"name": name, "error": proc.stderr.strip()[:200]})
            pulled.append({"name": name, "status": "failed"})

    return {
        "pulled": pulled,
        "errors": errors,
    }


# ── Mount ─────────────────────────────────────────────────────────────────────


# ── Ownership: what may this tool change or delete? (#415) ─────────────────────
#
# The rendered dirs are SHARED with native items (tracked skills, `sync-agents`
# output). A name list can never say what is safe to delete (#321 tried; it rotted),
# so ownership is read from the item itself:
#   * a symlink whose target text contains `projects/<member>/` (works when dangling), or
#   * a generated file carrying `<!-- opskit-member-render: <member> -->`, or (wrappers
#     rendered before the marker existed) frontmatter `member: <name>` with a filename
#     that starts `<name>-`.
# Anything else is not ours and is never modified or removed.

RENDER_MARKER_FMT = "<!-- opskit-member-render: {member} -->"
_RENDER_MARKER_RE = re.compile(r"<!--\s*opskit-member-render:\s*([a-z][a-z0-9-]*)\s*-->")
# Anchored: a render's link text is always `../…/projects/<member>/…` (relative, from a
# rendered dir). A native link that merely contains a `projects` path segment is not ours.
_PROJECTS_LINK_RE = re.compile(r"^(?:\.\./)+projects/([a-z][a-z0-9-]*)(?:/|$)")
# Wrappers rendered before the marker existed carry `member: <name>` in their frontmatter.
_LEGACY_MEMBER_FIELD_RE = re.compile(r"^member:\s*['\"]?([a-z][a-z0-9-]*)['\"]?\s*$", re.M)
_RENDER_SUBDIRS = (".opencode/agent", ".claude/agents", ".opencode/skills", ".claude/skills")


def member_of_render(path: Path) -> str | None:
    """Member that rendered `path`, or None if this tool did not create it."""
    try:
        if path.is_symlink():
            m = _PROJECTS_LINK_RE.match(os.readlink(path))
            return m.group(1) if m else None
        if path.is_file():
            with open(path, "r", errors="replace") as fh:
                text = fh.read(1 << 20)  # renders are small; do not miss a marker after a long description
            m = _RENDER_MARKER_RE.search(text)
            if m:
                return m.group(1)
            if text.startswith("---\n"):
                end = text.find("\n---", 4)
                legacy = _LEGACY_MEMBER_FIELD_RE.search(text[4:end] if end != -1 else "")
                if legacy and path.name.startswith(legacy.group(1) + "-"):
                    return legacy.group(1)
            return None
    except OSError:
        return None
    return None


def _root() -> Path:
    env = os.environ.get("OPSKIT_ROOT", "")
    return Path(env) if env else _PROJECTS.parent


def _is_tracked(root: Path, path: Path) -> bool | None:
    """True/False if git tracks `path`; None when that cannot be determined."""
    try:
        rel = os.path.relpath(str(path), str(root))
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
            capture_output=True, text=True,
        )
    except OSError:
        return None
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None  # not a repo / git failed: callers must fail safe


def _find_stale(root: Path, live_members: set[str]) -> list[tuple[Path, str]]:
    """Member renders whose member is gone from .project-remotes, or whose link dangles.

    Only direct children of the four rendered dirs, only items we provably created.
    """
    stale: list[tuple[Path, str]] = []
    for sub in _RENDER_SUBDIRS:
        d = root / sub
        if not d.is_dir():
            continue
        for child in sorted(d.iterdir()):
            owner = member_of_render(child)
            if owner is None:
                continue
            if owner not in live_members:
                stale.append((child, f"member '{owner}' is not in .project-remotes"))
            elif child.is_symlink() and not child.exists():
                stale.append((child, "dangling link (member not mounted in this checkout)"))
    return stale


def _rel(root: Path, path: Path) -> str:
    return os.path.relpath(str(path), str(root))


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split frontmatter from body. Returns (fm_dict, body_text)."""
    # Handle empty frontmatter (---\n---) and non-empty cases
    m = re.match(r"^---\n(.*?)(?:\n---\n)(.*)", text, re.DOTALL)
    if not m:
        # Try empty frontmatter: ---\n---\n body
        m2 = re.match(r"^---\n---\n(.*)", text, re.DOTALL)
        if m2:
            return {}, m2.group(1).lstrip("\n")
        return {}, text.lstrip("\n")
    data = yaml.safe_load(m.group(1))
    if not isinstance(data, dict):
        data = {}
    body = m.group(2) if m.group(2) else ""
    return data, body.lstrip("\n")


def _render_claude_agent_wrapper(
    name: str, fm: dict, body: str, member_name: str, trust: dict
) -> tuple[str, bool]:
    """Generate a Claude Code agent wrapper from a member's agent file.

    Translates frontmatter, injects trust overlay, adds member field.
    Returns (file_text, has_unenforceable_denies).
    """
    description = str(fm.get("description") or "").strip()
    triggers = str(fm.get("triggers") or "").strip()

    _SCALARS = ("bash", "edit", "write", "read")
    perm = fm.get("permission") if isinstance(fm.get("permission"), dict) else {}
    tool_perm = perm.get("tool") if isinstance(perm.get("tool"), dict) else {}

    flat_tools = {
        g: v for g, v in perm.items()
        if g not in _SCALARS and g != "tool" and isinstance(v, str)
    }
    tool_denies = [
        g for g, v in {**tool_perm, **flat_tools}.items() if v == "deny"
    ]
    scalar_denies = [k for k in _SCALARS if perm.get(k) == "deny"]

    base = description.rstrip().rstrip(".")
    desc = f"{base}. Use for: {triggers}." if triggers else description

    # Build trust overlay
    trust_bash = trust.get("bash", "ask")
    trust_tool_deny = list(trust.get("tool_deny", []))
    # Merge deny lists — include scalar denies (bash/other permission scalars)
    all_denies = list(set(tool_denies + scalar_denies + trust_tool_deny))

    fm_yaml = yaml.safe_dump(
        {"name": name, "description": desc, "member": member_name},
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=4096,
    ).strip()

    parts = [f"---\n{fm_yaml}\n---\n", RENDER_MARKER_FMT.format(member=member_name) + "\n"]
    if perm:
        parts.append(f"<!-- opencode-permission: {json.dumps(perm)} -->\n")

    # Add trust directive
    parts.append(f"# Trust overlay: bash={trust_bash}, tool_deny={all_denies}\n")

    parts.append(body.lstrip("\n"))

    has_soft = bool(all_denies)
    if has_soft:
        lines = [
            "\n\n## Tool restrictions (advisory under Claude Code)\n\n",
            "Claude Code does not hard-enforce OpenCode `permission` deny rules. "
            "Honor these behaviorally; hard enforcement needs a PreToolUse deny "
            "hook in `.claude/settings.json`.\n\n",
        ]
        lines += [f"- DENY tool `{g}`\n" for g in all_denies]
        parts.append("".join(lines))

    return "".join(parts), has_soft


def _skill_name(skill_dir: Path) -> str:
    """The name a host lists this skill under: frontmatter `name`, else the directory name.

    OpenCode lists by frontmatter name, not by directory (verified 2026-10-01), so the
    `<member>-` directory prefix does not namespace skills. Never raises on bad YAML.
    """
    try:
        fm, _ = _parse_frontmatter((skill_dir / "SKILL.md").read_text())
        name = fm.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        pass
    return skill_dir.name


def _native_skill_names(root: Path) -> dict[str, str]:
    """{skill name: repo-relative path} for every skill NOT rendered by a member."""
    names: dict[str, str] = {}
    for sub in (".opencode/skills", ".claude/skills"):
        d = root / sub
        if not d.is_dir():
            continue
        for child in sorted(d.iterdir()):
            if member_of_render(child) is not None or not child.is_dir():
                continue
            names.setdefault(_skill_name(child), _rel(root, child))
    return names


def exit_code(result: dict) -> int:
    """1 if a mount-shaped result has errors or conflicts (or sync failures); skips and stale are fine."""
    m = result.get("mount", result)
    bad = bool(m.get("errors")) or bool(m.get("conflicts"))
    sync = result.get("sync")
    if isinstance(sync, dict) and sync.get("summary", {}).get("failed", 0):
        bad = True
    return 1 if bad else 0


def cmd_mount(args: argparse.Namespace | None = None, dry_run: bool = False) -> dict:
    """Validate members and render their agents + skills.

    For each mounted member:
      1. Run opskit-aware.py check on the member root
      2. Render agents (symlinks for OpenCode, generated wrappers for Claude Code)
      3. Symlink skills into both discovery paths
    Then REPORT stale renders. Mount never deletes (#415): removal is `prune --force`.
    A destination that exists and was not rendered by a member is left alone and
    reported under `conflicts`.
    """
    _ROOT = _root()
    oc_dir = _ROOT / ".opencode" / "agent"
    cc_dir = _ROOT / ".claude" / "agents"
    oc_skills_dir = _ROOT / ".opencode" / "skills"
    cc_skills_dir = _ROOT / ".claude" / "skills"

    if not dry_run:
        for d in (oc_dir, cc_dir, oc_skills_dir, cc_skills_dir):
            d.mkdir(parents=True, exist_ok=True)

    remotes = parse_remotes(_REMOTES)
    mounted: list[dict] = []
    errors: list[dict] = []
    conflicts: list[dict] = []
    skipped: list[dict] = []
    created_links: list[tuple[str, Path]] = []
    taken_names = _native_skill_names(_ROOT)   # skill names already provided by non-member entries
    claimed_names: dict[str, str] = {}         # skill name -> member that rendered it this run

    def _link_target(link: Path, member: str, rel: str) -> str:
        # Relative to the link's own directory, and keeping `projects/<member>/` in the
        # text so the link is recognisable as ours even when it dangles.
        return os.path.relpath(str(_PROJECTS / member / rel), str(link.parent))

    def _can_write(dest: Path) -> bool:
        """True if dest is free or was rendered by a member; else record a conflict."""
        if dest.exists() or dest.is_symlink():
            if member_of_render(dest) is None:
                conflicts.append({"path": _rel(_ROOT, dest),
                                  "reason": "exists and was not rendered by a member; left untouched"})
                return False
        return True

    def _put_link(link: Path, target: str, member: str) -> bool:
        if not _can_write(link):
            return False
        if not dry_run:
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(target)
            created_links.append((member, link))
        return True

    for remote in remotes:
        name = remote["name"]
        local = _member_local_dir(remote)

        # Skip committed example/ reference
        if local == _EXAMPLE:
            mounted.append({"name": name, "status": "skipped", "reason": "committed reference"})
            continue

        # Skip unmounted members — run `sync` first to create mount links
        pack = _load_pack(_member_pack_path(local))
        if pack is None or not pack.get("name"):
            if pack is None:
                errors.append({"name": name, "error": "no pack.yml found"})
            else:
                errors.append({"name": name, "error": "pack.yml missing 'name' field"})
            continue
        if not _is_mounted(remote, pack):
            mounted.append({"name": name, "status": "unmounted", "reason": "no mount link (run sync first)"})
            continue

        # Validate pack.yml via opskit-aware.py check
        aware_path = _ROOT / "bin" / "opskit-aware.py"
        if aware_path.is_file():
            result = subprocess.run(
                [sys.executable, str(aware_path), "check", str(local)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                errors.append({
                    "name": name,
                    "error": "validation failed",
                    "details": result.stdout.strip()[:500],
                })
                continue

        trust = pack.get("trust", {}) or {}
        rendered_agents: list[str] = []
        rendered_skills: list[str] = []

        # ── Render agents ──
        for agent in (pack.get("agents") or []):
            if not isinstance(agent, dict) or not isinstance(agent.get("path"), str):
                continue
            agent_rel = agent["path"]
            agent_file = local / agent_rel
            if not agent_file.is_file():
                errors.append({"name": name, "error": f"agent missing: {agent_rel}"})
                continue

            # Parse frontmatter to check mode
            fm, body = _parse_frontmatter(agent_file.read_text())
            if fm.get("mode") not in ("subagent",):
                reason = "no `mode: subagent` in frontmatter (OpenCode dialect); not rendered"
                rendered_agents.append({"name": name, "agent": agent_rel, "status": "skipped", "reason": reason})
                skipped.append({"member": name, "kind": "agent", "item": agent_rel, "reason": reason})
                continue

            base_name = agent_file.stem
            # OpenCode: symlink
            oc_link = oc_dir / f"{name}-{base_name}.md"
            oc_ok = _put_link(oc_link, _link_target(oc_link, name, agent_rel), name)

            # Claude Code: generate wrapper
            cc_text, _ = _render_claude_agent_wrapper(
                name=f"{name}-{base_name}",
                fm=fm,
                body=body,
                member_name=name,
                trust=trust,
            )
            cc_file = cc_dir / f"{name}-{base_name}.md"
            cc_ok = _can_write(cc_file)
            if cc_ok and not dry_run:
                cc_file.write_text(cc_text)

            rendered_agents.append({"name": name, "agent": agent_rel,
                                    "status": "rendered" if (oc_ok and cc_ok) else "conflict"})

        # ── Render skills ──
        for skill in (pack.get("skills") or []):
            if not isinstance(skill, dict) or not isinstance(skill.get("path"), str):
                continue
            skill_rel = skill["path"]
            skill_dir = local / skill_rel
            if not skill_dir.is_dir():
                errors.append({"name": name, "error": f"skill dir missing: {skill_rel}"})
                continue

            prefix = f"{name}-{skill_dir.name}"
            sname = _skill_name(skill_dir)
            clash = taken_names.get(sname)
            if clash is None and claimed_names.get(sname, name) != name:
                clash = f"member '{claimed_names[sname]}'"
            if clash is not None:
                conflicts.append({"path": _rel(_ROOT, oc_skills_dir / prefix),
                                  "reason": f"skill name '{sname}' already provided by {clash}; not rendered"})
                rendered_skills.append({"name": name, "skill": skill_rel, "status": "conflict"})
                continue
            claimed_names[sname] = name
            ok = True
            for skills_dir in (oc_skills_dir, cc_skills_dir):
                link = skills_dir / prefix
                ok = _put_link(link, _link_target(link, name, skill_rel), name) and ok

            rendered_skills.append({"name": name, "skill": skill_rel,
                                    "status": "rendered" if ok else "conflict"})

        mounted.append({
            "name": name,
            "status": "mounted",
            "agents_rendered": sum(1 for a in rendered_agents if a.get("status") == "rendered"),
            "skills_rendered": sum(1 for k in rendered_skills if k.get("status") == "rendered"),
            "rendered_agents": rendered_agents,
            "rendered_skills": rendered_skills,
        })

    # ── Every link we created must resolve, or the tool reported success it did not achieve ──
    for member, link in created_links:
        if not link.exists():
            errors.append({"name": member,
                           "error": f"rendered link does not resolve: {_rel(_ROOT, link)} -> {os.readlink(link)}"})

    # ── Report stale renders (never delete here) ──
    stale = [_rel(_ROOT, p) for p, _ in _find_stale(_ROOT, {r["name"] for r in remotes})]

    total_agents = sum(m.get("agents_rendered", 0) for m in mounted if m.get("status") == "mounted")
    total_skills = sum(m.get("skills_rendered", 0) for m in mounted if m.get("status") == "mounted")

    return {
        "mounted": mounted,
        "errors": errors,
        "conflicts": conflicts,
        "skipped": skipped,
        "stale": stale,
        "pruned": [],
        "dry_run": dry_run,
        "summary": {
            "total": len(remotes),
            "mounted": sum(1 for m in mounted if m.get("status") == "mounted"),
            "skipped": sum(1 for m in mounted if m.get("status") == "skipped"),
            "errors": len(errors),
            "conflicts": len(conflicts),
            "items_skipped": len(skipped),
            "agents_rendered": total_agents,
            "skills_rendered": total_skills,
            "stale": len(stale),
            "pruned": 0,
        },
        "note": ("Stale member renders found; mount never deletes. Review with "
                 "`prune`, remove with `prune --force`." if stale else ""),
    }


def cmd_prune(args: argparse.Namespace | None = None, force: bool = False, dry_run: bool = False) -> dict:
    """Report stale member renders; with force=True remove them.

    A path is removed only if ALL hold: it is a stale member render (see
    member_of_render), it is a symlink or a plain file (never rmtree), git does not
    track it, and tracking could be verified (not a repo => remove nothing).
    """
    root = _root()
    remotes = parse_remotes(_REMOTES)
    stale = _find_stale(root, {r["name"] for r in remotes})
    removed: list[str] = []
    skipped: list[dict] = []
    for path, why in stale:
        rel = _rel(root, path)
        tracked = _is_tracked(root, path)
        if tracked is None:
            skipped.append({"path": rel, "reason": "cannot verify tracked state (not a git repo?); left in place"})
        elif tracked:
            skipped.append({"path": rel, "reason": "tracked by git; never removed"})
        elif path.is_dir() and not path.is_symlink():
            skipped.append({"path": rel, "reason": "is a directory; refusing to rmtree"})
        elif force and not dry_run:
            path.unlink()
            removed.append(rel)
    return {
        "stale": [_rel(root, p) for p, _ in stale],
        "reasons": {_rel(root, p): why for p, why in stale},
        "removed": removed,
        "skipped": skipped,
        "dry_run": dry_run,
        "summary": {"stale": len(stale), "removed": len(removed), "skipped": len(skipped)},
        "note": ("" if force else "Report only. Re-run with --force to remove the stale items listed."),
    }


# ── Sync + Mount ──────────────────────────────────────────────────────────────


def cmd_sync_mount(args: argparse.Namespace | None = None) -> dict:
    """Sync members (clone/pull + symlink) then mount (validate + render)."""
    sync_result = cmd_sync()
    mount_result = cmd_mount()

    return {
        "sync": sync_result,
        "mount": mount_result,
        "summary": {
            "synced": sync_result.get("summary", {}).get("synced", 0),
            "failed": sync_result.get("summary", {}).get("failed", 0),
            "mounted": mount_result.get("summary", {}).get("mounted", 0),
            "pruned": mount_result.get("summary", {}).get("pruned", 0),
        },
    }


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage OpsKit member repos (clone/pull/symlink + mount).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # status
    ps = sub.add_parser("status", help="show mount state per member")
    ps.set_defaults(fn=lambda a: cmd_status())

    # sync
    ps = sub.add_parser("sync", help="clone/pull members + create/update symlinks")
    ps.set_defaults(fn=lambda a: cmd_sync())

    # pull
    ps = sub.add_parser("pull", help="pull updates for clone members")
    ps.set_defaults(fn=lambda a: cmd_pull())

    # mount — validate members, render agents/skills, prune stale
    pm = sub.add_parser("mount", help="validate + render agents/skills; reports stale, never deletes")
    pm.add_argument("--dry-run", action="store_true", help="show what would be rendered; change nothing")
    pm.set_defaults(fn=lambda a: cmd_mount(dry_run=a.dry_run))

    # prune — report stale member renders; --force removes them
    pp = sub.add_parser("prune", help="report stale member renders (--force to remove)")
    pp.add_argument("--force", action="store_true", help="actually remove the stale items")
    pp.add_argument("--dry-run", action="store_true", help="with --force: still remove nothing")
    pp.set_defaults(fn=lambda a: cmd_prune(force=a.force, dry_run=a.dry_run))

    # sync-mount — sync + mount in one step
    psm = sub.add_parser("sync-mount", help="sync + mount in one step")
    psm.set_defaults(fn=lambda a: cmd_sync_mount())

    args = parser.parse_args()
    result = args.fn(args)
    _emit(result)
    return exit_code(result) if args.cmd in ("mount", "sync-mount") else 0


if __name__ == "__main__":
    sys.exit(main())
