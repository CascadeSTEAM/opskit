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
