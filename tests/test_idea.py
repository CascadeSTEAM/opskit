"""Tests for bin/idea.py — the idea-capture ledger CLI."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDEA = ROOT / "bin" / "idea.py"

LEDGER_HEADER = (
    "# Test Ledger\n\n"
    "| Date | Desire (1-5) | Title | Description | Status | GH# |\n"
    "|------|--------------|-------|-------------|--------|-----|\n"
)


def run(ledger: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(IDEA), "--file", str(ledger), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ideas.md"
    path.write_text(LEDGER_HEADER)
    return path


class TestAdd:
    def test_add_appends_row(self, ledger):
        result = run(ledger, "add", "--desire", "4", "--title", "Auto context gen", "--desc", "Render context/ from datasets")
        assert result.returncode == 0, result.stderr
        assert "added row 1" in result.stdout
        assert "| Auto context gen |" in ledger.read_text()
        assert "| new |" in ledger.read_text()

    def test_pipes_escaped_round_trip(self, ledger):
        title = "a|b pipe title"
        run(ledger, "add", "--desire", "2", "--title", title, "--desc", "d")
        assert "a\\|b pipe title" in ledger.read_text()
        result = run(ledger, "search", "pipe")
        assert title in result.stdout


class TestListSearch:
    def test_list_filters_by_status(self, ledger):
        run(ledger, "add", "--desire", "3", "--title", "one", "--desc", "d1")
        run(ledger, "add", "--desire", "5", "--title", "two", "--desc", "d2")
        run(ledger, "mark", "--row", "1", "--status", "accepted", "--gh", "42")
        result = run(ledger, "list", "--status", "new")
        assert "two" in result.stdout and "one" not in result.stdout

    def test_list_min_desire(self, ledger):
        run(ledger, "add", "--desire", "1", "--title", "low", "--desc", "d")
        run(ledger, "add", "--desire", "5", "--title", "high", "--desc", "d")
        result = run(ledger, "list", "--min-desire", "4")
        assert "high" in result.stdout and "low" not in result.stdout

    def test_search_all_words_must_match(self, ledger):
        run(ledger, "add", "--desire", "3", "--title", "nmap scan speedup", "--desc", "cache results")
        assert "speedup" in run(ledger, "search", "nmap", "cache").stdout
        assert "no ideas matched" in run(ledger, "search", "nmap", "zebra").stdout


class TestMark:
    def test_mark_by_row_sets_status_and_gh(self, ledger):
        run(ledger, "add", "--desire", "3", "--title", "t", "--desc", "d")
        result = run(ledger, "mark", "--row", "1", "--status", "consolidated", "--gh", "7")
        assert result.returncode == 0
        assert "| consolidated | 7 |" in ledger.read_text()

    def test_mark_with_reason(self, ledger):
        run(ledger, "add", "--desire", "1", "--title", "meh", "--desc", "d")
        run(ledger, "mark", "--row", "1", "--status", "declined", "--reason", "out of scope")
        assert "declined (out of scope)" in ledger.read_text()

    def test_mark_out_of_range_fails(self, ledger):
        result = run(ledger, "mark", "--row", "9", "--status", "accepted")
        assert result.returncode != 0

    def test_mark_ambiguous_title_fails(self, ledger):
        run(ledger, "add", "--desire", "2", "--title", "dup", "--desc", "a")
        run(ledger, "add", "--desire", "2", "--title", "dup", "--desc", "b")
        result = run(ledger, "mark", "--title", "dup", "--status", "accepted")
        assert result.returncode != 0 and "ambiguous" in result.stderr


class TestRealLedger:
    def test_repo_ledger_parses(self):
        result = run(ROOT / "docs" / "ideas.md", "list")
        assert result.returncode == 0
