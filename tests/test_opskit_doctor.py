"""Tests for `opskit doctor` — self-diagnostic battery (issue #311)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"

# PATH with bw and uvx available so doctor returns 0
TEST_PATH = "/usr/local/bin:/home/netyeti/.local/bin:/usr/bin:/bin"
TEST_ENV = {"PATH": TEST_PATH, "OPSKIT_ROOT": str(ROOT)}


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(OPSKIT), *args],
        capture_output=True,
        text=True,
        env=env or TEST_ENV,
    )


class TestDoctorBasic:
    """Smoke tests for the doctor subcommand."""

    def test_doctor_help(self):
        r = run_cli("--help")
        assert r.returncode == 0
        assert "doctor" in r.stdout

    def test_doctor_exits_clean(self):
        """Doctor should exit 0 when all checks pass (PATH has deps)."""
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "MCP launch paths:" in r.stdout

    def test_doctor_with_prune(self):
        """Doctor with --prune runs merge-time cleanup."""
        r = run_cli("doctor", "--prune")
        assert r.returncode == 0
        assert "Merge-time cleanup:" in r.stdout


class TestDoctorOutput:
    """Verify doctor output format."""

    def test_doctor_reports_mcp_status(self):
        """Doctor should report MCP server status."""
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "MCP" in r.stdout or "mcp" in r.stdout.lower()

    def test_doctor_reports_hooks(self):
        """Doctor should report git hooksPath status."""
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "hooks" in r.stdout.lower()

    def test_doctor_reports_yaml_lint(self):
        """Doctor should report skill frontmatter lint status."""
        r = run_cli("doctor")
        assert r.returncode == 0
        assert "frontmatter" in r.stdout.lower() or "yaml" in r.stdout.lower()
