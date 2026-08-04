"""Tests for bin/automation-ladder.py sync-agents — offline, in tmp_path.

REPO_ROOT is overridden via OPSKIT_ROOT so a fake agents/ tree is rendered
into a temp checkout; no real .opencode/.claude dirs are touched. The CLI is
invoked with the same interpreter running pytest (sys.executable) so PyYAML
from the test venv is guaranteed available.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LADDER = ROOT / "bin" / "automation-ladder.py"

AGENT_WITH_TOOL_DENY = """\
---
description: Manages MikroTik devices — switches and routers
tags: [mikrotik]
mode: subagent
triggers: mikrotik,routeros
permission:
  tool:
    "relay-shell_*": deny
    "mikromcp_*": allow
tools:
  skill: true
---

Body about MikroTik.
"""

AGENT_WITH_SCALAR_DENY = """\
---
description: Handles lifecycle transitions.
mode: subagent
triggers: lifecycle,plan
permission:
  bash: deny
---

Lifecycle body.
"""

NOT_A_SUBAGENT = """\
---
description: Just a reference doc
mode: skill
---

Not mounted.
"""


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["OPSKIT_ROOT"] = str(root)
    return subprocess.run(
        [sys.executable, str(LADDER), *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "opskit"
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "mikrotik.md").write_text(AGENT_WITH_TOOL_DENY)
    (root / "agents" / "lifecycle.md").write_text(AGENT_WITH_SCALAR_DENY)
    (root / "agents" / "notes.md").write_text(NOT_A_SUBAGENT)
    return root


class TestSyncAgents:
    def test_creates_both_targets(self, repo):
        r = run(repo, "sync-agents")
        assert r.returncode == 0, r.stdout + r.stderr
        out = json.loads(r.stdout)
        assert set(out["synced"]) == {"mikrotik", "lifecycle"}
        assert out["skipped"] == ["notes"]
        assert (repo / ".opencode" / "agent" / "mikrotik.md").is_symlink()
        assert (repo / ".claude" / "agents" / "mikrotik.md").is_file()

    def test_opencode_symlink_points_to_canonical(self, repo):
        run(repo, "sync-agents")
        link = repo / ".opencode" / "agent" / "mikrotik.md"
        assert os.readlink(link) == str(Path("../../agents") / "mikrotik.md")
        assert link.resolve() == (repo / "agents" / "mikrotik.md").resolve()

    def test_claude_agent_has_name_and_folded_triggers(self, repo):
        run(repo, "sync-agents")
        text = (repo / ".claude" / "agents" / "mikrotik.md").read_text()
        assert "name: mikrotik" in text
        assert "Use for: mikrotik,routeros" in text
        # canonical body is carried through
        assert "Body about MikroTik." in text

    def test_tool_deny_preserved_and_flagged(self, repo):
        r = run(repo, "sync-agents")
        out = json.loads(r.stdout)
        assert "mikrotik" in out["soft_sandbox_warning"]
        text = (repo / ".claude" / "agents" / "mikrotik.md").read_text()
        assert "opencode-permission:" in text
        assert "relay-shell_*" in text  # intent preserved in the comment
        assert "DENY tool `relay-shell_*`" in text
        assert "advisory under Claude Code" in text

    def test_flat_tool_deny_is_read(self, repo):
        """Tool globs directly under `permission` are the shape OpenCode honours
        in an agent file; a nested `permission.tool:` block is silently ignored
        there. The Claude renderer must read the flat form, or the restriction
        notice silently disappears for exactly the agents that need it."""
        (repo / "agents" / "flat.md").write_text(
            "---\n"
            "description: Flat permission form\n"
            "mode: subagent\n"
            "triggers: flat\n"
            "permission:\n"
            '  "relay-shell_*": deny\n'
            '  "mikromcp_*": allow\n'
            "---\n\nBody.\n"
        )
        out = json.loads(run(repo, "sync-agents").stdout)
        assert "flat" in out["soft_sandbox_warning"]
        text = (repo / ".claude" / "agents" / "flat.md").read_text()
        assert "DENY tool `relay-shell_*`" in text
        assert "DENY tool `mikromcp_*`" not in text, "an allow must not be reported as a deny"

    def test_scalar_bash_deny_flagged(self, repo):
        out = json.loads(run(repo, "sync-agents").stdout)
        assert "lifecycle" in out["soft_sandbox_warning"]
        text = (repo / ".claude" / "agents" / "lifecycle.md").read_text()
        assert "DENY `bash`" in text

    def test_regeneration_is_idempotent(self, repo):
        run(repo, "sync-agents")
        first = (repo / ".claude" / "agents" / "mikrotik.md").read_text()
        r2 = run(repo, "sync-agents")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        link = repo / ".opencode" / "agent" / "mikrotik.md"
        assert link.is_symlink()
        assert (repo / ".claude" / "agents" / "mikrotik.md").read_text() == first

    def test_missing_agents_dir_errors(self, tmp_path):
        r = run(tmp_path / "empty", "sync-agents")
        assert r.returncode != 0
        assert "does not exist" in r.stdout


class TestBackwardCompat:
    def test_status_still_works(self, repo):
        r = run(repo, "status")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "thresholds" in r.stdout


class TestCanonicalAgentsAreLoadable:
    """Guards against the defect this feature shipped with: the two
    domain-enforcement agents declared their tool globs under a nested
    `permission.tool:` block, which OpenCode silently ignores in an agent file.
    The global `mikromcp_*: deny` therefore stayed in force and the mikrotik
    agent could not reach a single MikroTik device — while AGENTS.md advertised
    the denies as runtime-enforced. Same class as the ansible-lint config in
    #83: configuration in a shape the tool quietly disregards.
    """

    @staticmethod
    def _frontmatter(path: Path) -> dict:
        import re

        import yaml

        m = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.DOTALL)
        assert m, f"{path.name} has no YAML frontmatter"
        return yaml.safe_load(m.group(1)) or {}

    def test_no_canonical_agent_nests_tool_permissions(self):
        offenders = []
        for src in sorted((ROOT / "agents").glob("*.md")):
            perm = self._frontmatter(src).get("permission")
            if isinstance(perm, dict) and isinstance(perm.get("tool"), dict):
                offenders.append(src.name)
        assert not offenders, (
            f"{offenders} nest tool globs under `permission.tool:`. OpenCode "
            f"ignores that in an agent file, so the rules never apply. Put the "
            f"globs directly under `permission:` instead."
        )

    def test_domain_agents_still_declare_their_enforcement(self):
        """AGENTS.md promises @mikrotik cannot reach relay-shell and @linux
        cannot reach mikromcp. If those globs vanish, the docs become false."""
        mikrotik = self._frontmatter(ROOT / "agents" / "mikrotik.md").get("permission") or {}
        linux = self._frontmatter(ROOT / "agents" / "linux.md").get("permission") or {}
        assert mikrotik.get("relay-shell_*") == "deny"
        assert mikrotik.get("mikromcp_*") == "allow", (
            "without an explicit allow the global mikromcp_* deny wins and this "
            "agent cannot reach any MikroTik device"
        )
        assert linux.get("mikromcp_*") == "deny"
