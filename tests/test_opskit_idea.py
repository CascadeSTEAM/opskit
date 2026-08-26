"""Tests for `opskit idea` — context-aware ledger capture."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
OPSKIT = ROOT / "bin" / "opskit"

LEDGER_HEADER = (
    "# Idea Ledger\n\n"
    "| Date | Desire (1-5) | Title | Description | Status | GH# |\n"
    "|------|--------------|-------|-------------|--------|-----|\n"
)


def run_idea(*extra: str, tmp_root: Path = None, ledger: Path = None, cwd: Path = None,
             env_overrides: dict = None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin"}
    if tmp_root:
        env["OPSKIT_ROOT"] = str(tmp_root)
    if ledger:
        env_overrides = env_overrides or {}
        env.update(env_overrides)
    cmd = [sys.executable, str(OPSKIT), "idea", *extra]
    if ledger:
        cmd += ["--ledger", str(ledger)]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd, timeout=30)


class TestOpskitIdeaContext:
    def test_idea_explicit_ledger_adds_to_it(self, tmp_path: Path):
        """--ledger flag controls where the idea is added."""
        ledger = tmp_path / "custom-ideas.md"
        ledger.write_text(LEDGER_HEADER)
        result = run_idea("test explicit ledger", "--desire", "3", ledger=ledger)
        assert result.returncode == 0, result.stderr
        assert "✓ Added" in result.stdout
        assert "test explicit ledger" in ledger.read_text()

    def test_idea_creates_ledger_if_missing(self, tmp_path: Path):
        """When ledger doesn't exist, it's created with a minimal header."""
        ledger = tmp_path / "no-ideas-yet.md"
        result = run_idea("test ledger creation", "--desire", "3", ledger=ledger)
        assert result.returncode == 0, result.stderr
        assert ledger.exists()
        assert "# Idea Ledger" in ledger.read_text()
        assert "test ledger creation" in ledger.read_text()

    def test_idea_dedupe_shows_matches_and_cancels(self, tmp_path: Path):
        """When dedupe finds a match, it shows it and asks to cancel."""
        ledger = tmp_path / "ideas.md"
        # "theme" is the last word of the existing row's title
        ledger.write_text(
            LEDGER_HEADER
            + "| 2026-07-20 | 3 | Dark mode theme | enable dark theme | new | |\n"
        )
        # Last word "theme" matches "theme" in the existing row's haystack
        result = run_idea("Add dark mode theme", "--desire", "3", ledger=ledger)
        assert result.returncode == 0
        assert "Potential duplicates found" in result.stdout
        assert "Cancelled" in result.stdout

    def test_idea_dedupe_no_match_adds_new(self, tmp_path: Path):
        """When dedupe finds no match, new idea is added."""
        ledger = tmp_path / "ideas.md"
        ledger.write_text(
            LEDGER_HEADER
            + "| 2026-07-20 | 3 | Existing feature | something | new | |\n"
        )
        # Last word "foobar" won't match anything
        result = run_idea("xyzzy foobar", "--desire", "3", ledger=ledger)
        assert result.returncode == 0, result.stderr
        assert "✓ Added" in result.stdout
        assert "xyzzy foobar" in ledger.read_text()

    def test_idea_empty_text_rejected(self):
        """Empty idea text is rejected."""
        result = run_idea("", "--desire", "3")
        assert result.returncode != 0
        assert "ERROR" in result.stderr
