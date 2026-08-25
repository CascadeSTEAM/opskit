"""Tests for bin/project_sync.py — member repo management (sync/pull/status).

Runs offline in tmp_path. Uses pytest's tmp_path fixture.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Ensure we can import from bin/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import project_sync as ps


@pytest.fixture(autouse=True)
def _restore_module_state():
    """Restore module-level constants after each test."""
    orig_remotes = ps._REMOTES
    orig_projects = ps._PROJECTS
    orig_example = ps._EXAMPLE
    yield
    ps._REMOTES = orig_remotes
    ps._PROJECTS = orig_projects
    ps._EXAMPLE = orig_example


@pytest.fixture
def tmp_member(tmp_path: Path) -> Path:
    """Create a minimal OpsKit-aware member."""
    member = tmp_path / "member"
    member.mkdir()
    opskit_dir = member / ".opskit"
    opskit_dir.mkdir()

    pack = {
        "contract": 1,
        "name": "test-member",
        "description": "Test member",
        "data_classification": "public",
        "sync": "symlink",
        "agents": [{"path": "agents/test.md"}],
        "skills": [{"path": "skills/test-skill"}],
        "trust": {"bash": "ask", "tool_deny": []},
    }
    (opskit_dir / "pack.yml").write_text(yaml.safe_dump(pack))

    agents = member / "agents"
    agents.mkdir()
    (agents / "test.md").write_text("---\nmode: subagent\nname: test\n---\n\nTest\n")

    skills = member / "skills" / "test-skill"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: test-skill\nmode: skill\n---\n\nTest skill\n")

    return member


# ── parse_remotes ────────────────────────────────────────────────────────────


class TestParseRemotes:

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("")
        assert ps.parse_remotes(f) == []

    def test_comments_and_blanks(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("# Comment\n\ntest-member /some/path\n  \n# Another comment\n")
        result = ps.parse_remotes(f)
        assert len(result) == 1
        assert result[0]["name"] == "test-member"
        assert result[0]["path"] == "/some/path"

    def test_malformed_line(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("only-one-field\n")
        result = ps.parse_remotes(f)
        assert result == []

    def test_pin_field(self, tmp_path: Path):
        f = tmp_path / ".project-remotes"
        f.write_text("my-member git@github.com:foo/bar.git v1.0\n")
        result = ps.parse_remotes(f)
        assert len(result) == 1
        assert result[0]["name"] == "my-member"
        assert result[0]["pin"] == "v1.0"


# ── _member_local_dir ────────────────────────────────────────────────────────


class TestMemberLocalDir:

    def test_absolute_path(self):
        remote = {"path": "/absolute/path"}
        result = ps._member_local_dir(remote)
        assert result == Path("/absolute/path")

    def test_tilde_expansion(self):
        remote = {"path": "~/test-path"}
        result = ps._member_local_dir(remote)
        assert result == Path.home() / "test-path"

    def test_relative_path_resolves_to_repo_root(self):
        # Relative paths resolve against REPO_ROOT (module-level constant).
        remote = {"path": "relative/path"}
        result = ps._member_local_dir(remote)
        assert result == ps.REPO_ROOT / "relative/path"


# ── _is_mounted ──────────────────────────────────────────────────────────────


class TestIsMounted:

    def test_no_dir(self, tmp_path: Path):
        remotes = [{"name": "x", "path": str(tmp_path / "nope")}]
        assert ps._is_mounted(remotes[0], {"name": "x"}) is False

    def test_mounted_symlink(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        link = ps._PROJECTS / "test-member"
        link.symlink_to(tmp_member)

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], {"name": "test-member"}) is True

    def test_mounted_no_link(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        # No symlink created

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], {"name": "test-member"}) is False

    def test_skips_example_ref(self, tmp_path: Path):
        example = tmp_path / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        ps._EXAMPLE = example
        ps._PROJECTS = tmp_path / "projects"

        remotes = [{"name": "example", "path": str(example)}]
        assert ps._is_mounted(remotes[0], {"name": "example"}) is False

    def test_no_pack(self, tmp_member: Path):
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._PROJECTS.mkdir()
        (ps._PROJECTS / "test-member").symlink_to(tmp_member)

        remotes = [{"name": "test-member", "path": str(tmp_member)}]
        assert ps._is_mounted(remotes[0], None) is False


# ── Status ───────────────────────────────────────────────────────────────────


class TestStatus:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_status()
        assert result["summary"]["total"] == 0
        assert "No members" in result["note"]

    def test_one_member_missing(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        ps._REMOTES = remotes
        ps._PROJECTS = tmp_path / "projects"

        result = ps.cmd_status()
        assert result["summary"]["total"] == 1
        assert result["summary"]["missing"] == 1
        assert result["members"][0]["state"] == "missing"

    def test_skips_example_in_status(self, tmp_member: Path):
        # Create example dir that matches ps._EXAMPLE
        example = tmp_member.parent / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"example {example}\n")
        ps._REMOTES = remotes
        ps._PROJECTS = tmp_member.parent / "projects"
        ps._EXAMPLE = example

        result = ps.cmd_status()
        assert result["summary"]["skipped"] == 1
        assert result["members"][0]["state"] == "skipped"


# ── Sync ─────────────────────────────────────────────────────────────────────


class TestSync:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_sync()
        assert "No members" in result["note"]

    def test_symlink_member(self, tmp_path: Path, tmp_member: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert result["summary"]["failed"] == 0
        assert len(result["synced"]) == 1
        assert result["synced"][0]["status"] == "symlinked"
        link = projects / "test-member"
        assert link.is_symlink()
        assert link.resolve() == tmp_member.resolve()

    def test_skips_example(self, tmp_member: Path):
        example = tmp_member.parent / "projects" / "example"
        example.mkdir(parents=True)
        (example / ".opskit").mkdir()
        (example / ".opskit" / "pack.yml").write_text("name: example\n")

        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"example {example}\n")
        projects = tmp_member.parent / "projects"
        ps._REMOTES = remotes
        ps._PROJECTS = projects
        ps._EXAMPLE = example

        result = ps.cmd_sync()
        assert result["synced"][0]["status"] == "skipped"

    def test_missing_symlink_source(self, tmp_path: Path):
        remotes = tmp_path / ".project-remotes"
        remotes.write_text("ghost-member /nonexistent/path\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert len(result["synced"]) == 1
        assert result["synced"][0]["status"] == "missing_source"

    def test_clone_member(self, tmp_path: Path):
        """Clone a git repo into members dir and create mount symlink."""
        # Create a source git repo (will be cloned)
        src_repo = tmp_path / "src-repo"
        src_repo.mkdir()
        subprocess.run(["git", "init"], cwd=src_repo, capture_output=True, check=True)
        (src_repo / "README").write_text("hi")
        subprocess.run(["git", "-C", str(src_repo), "add", "."], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(src_repo), "commit", "-m", "init"], capture_output=True, check=True)

        # Remotes: name + local-path-as-URL for clone.
        # We point to src_repo. _member_local_dir returns it as an absolute path.
        # Since src_repo IS a git repo, _git_pull will work (it's already "cloned").
        remotes = tmp_path / ".project-remotes"
        remotes.write_text(f"clone-member {src_repo}\n")
        projects = tmp_path / "projects"
        projects.mkdir()
        ps._REMOTES = remotes
        ps._PROJECTS = projects

        result = ps.cmd_sync()
        assert result["summary"]["failed"] == 0
        assert len(result["synced"]) == 1
        # No pack.yml exists at src_repo, so is_clone=False → symlink mode
        assert result["synced"][0]["status"] == "symlinked"


# ── Pull ─────────────────────────────────────────────────────────────────────


class TestPull:

    def test_no_remotes(self, tmp_path: Path):
        ps._REMOTES = tmp_path / "empty"
        ps._REMOTES.write_text("")

        result = ps.cmd_pull()
        assert len(result["pulled"]) == 0

    def test_skips_non_clone(self, tmp_member: Path):
        remotes = tmp_member.parent / ".project-remotes"
        remotes.write_text(f"test-member {tmp_member}\n")
        ps._REMOTES = remotes

        result = ps.cmd_pull()
        assert len(result["pulled"]) == 1
        assert result["pulled"][0]["status"] == "skipped"
        assert result["pulled"][0]["reason"] == "not clone mode"
