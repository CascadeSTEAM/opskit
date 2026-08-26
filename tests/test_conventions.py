"""Tests for bin/conventions.py — scaffold + drift check for repo-shape files."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "bin" / "conventions.py"


def run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["OPSKIT_ROOT"] = str(ROOT)
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


class TestScaffold:
    def test_scaffolds_all_convention_files(self, tmp_path):
        target = tmp_path / "new-repo"
        r = run("scaffold", str(target))
        assert r.returncode == 0, r.stdout + r.stderr
        assert (target / "AGENTS.md").is_file()
        assert (target / "CLAUDE.md").is_file()
        assert (target / ".opencode" / "skills" / ".gitkeep").is_file()
        assert (target / ".opencode" / "agent" / ".gitkeep").is_file()
        assert (target / ".githooks" / "pre-commit").is_file()
        assert (target / ".githooks" / "pre-commit").stat().st_mode & 0o111
        assert (target / "docs" / "session-log-lifecycle.md").is_file()

    def test_refuses_non_empty_target(self, tmp_path):
        target = tmp_path / "existing"
        target.mkdir()
        (target / "README.md").write_text("hello\n")
        r = run("scaffold", str(target))
        assert r.returncode != 0
        assert "already exists and is non-empty" in r.stderr

    def test_creates_empty_dir_if_missing(self, tmp_path):
        target = tmp_path / "a" / "b" / "new-repo"
        r = run("scaffold", str(target))
        assert r.returncode == 0
        assert (target / "AGENTS.md").is_file()

    def test_scaffolded_agents_has_all_required_sections(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        content = (target / "AGENTS.md").read_text()
        required = [
            "Behavioral Hard Rule",
            "Core Rules",
            "Environment Model",
            "Tool Scripts",
            "Subagents",
            "Skills",
            "Development Principles",
            "Git & GitHub Workflow",
            "Lifecycle Rules",
            "Helpdesk Ticket Tracking",
        ]
        for section in required:
            assert section in content, f"missing section: {section}"

    def test_scaffolded_claude_has_all_required_sections(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        content = (target / "CLAUDE.md").read_text()
        required = [
            "Infrastructure",
            "Verify Before Claiming",
            "Core Rules",
            "Environment Model",
            "Tool Scripts",
            "Subagents",
            "Skills",
            "Development Principles",
            "Git & GitHub Workflow",
            "Lifecycle Rules",
            "Helpdesk Ticket Tracking",
        ]
        for section in required:
            assert section in content, f"missing section: {section}"


class TestCheck:
    def test_passes_on_full_scaffold(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        r = run("check", "--repo", str(target))
        assert r.returncode == 0, r.stdout + r.stderr

    def test_finds_missing_agents_md(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        (target / "AGENTS.md").unlink()
        r = run("check", "--repo", str(target))
        assert r.returncode != 0
        assert "MISSING: AGENTS.md" in r.stdout

    def test_finds_missing_section(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        content = (target / "AGENTS.md").read_text()
        # Remove one required section
        content = content.replace("## Lifecycle Rules", "# Lifecycle Rules")
        (target / "AGENTS.md").write_text(content)
        r = run("check", "--repo", str(target))
        assert r.returncode != 0
        assert "MISSING SECTION" in r.stdout
        assert "Lifecycle Rules" in r.stdout

    def test_finds_missing_githooks_precommit(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        (target / ".githooks" / "pre-commit").unlink()
        r = run("check", "--repo", str(target))
        assert r.returncode != 0
        assert ".githooks/pre-commit" in r.stdout

    def test_check_cwd_defaults_to_current_dir(self, tmp_path):
        """Running `check` without --repo uses cwd."""
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        r = run("check", cwd=str(target))
        assert r.returncode == 0, r.stdout + r.stderr

    def test_refuses_non_directory(self, tmp_path):
        target = tmp_path / "not-a-dir"
        target.touch()
        r = run("check", "--repo", str(target))
        assert r.returncode != 0
        assert "not a directory" in r.stderr

    def test_reports_multiple_issues(self, tmp_path):
        target = tmp_path / "new-repo"
        run("scaffold", str(target))
        (target / "AGENTS.md").unlink()
        (target / ".githooks" / "pre-commit").unlink()
        r = run("check", "--repo", str(target))
        assert r.returncode != 0
        # Both required files are missing
        assert r.stdout.count("MISSING") >= 2


class TestIntegration:
    def test_opskit_repo_passes_check(self):
        """The real opskit repo should pass the drift check."""
        r = run("check", "--repo", str(ROOT))
        assert r.returncode == 0, r.stdout + r.stderr
