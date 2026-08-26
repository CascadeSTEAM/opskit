"""Tests for bin/idea-cmd.py — interactive capture + dedupe CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDEA_CMD = ROOT / "bin" / "idea-cmd.py"
IDEA_PY = ROOT / "bin" / "idea.py"

LEDGER_HEADER = (
    "# Test Ledger\n\n"
    "| Date | Desire (1-5) | Title | Description | Status | GH# |\n"
    "|------|--------------|-------|-------------|--------|-----|\n"
)


def run(*args: str, ledger: Path = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(IDEA_CMD), *args]
    if ledger:
        cmd = [sys.executable, str(IDEA_CMD), "--file", str(ledger), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


def run_idea(*args: str, ledger: Path = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(IDEA_PY)]
    if ledger:
        # --file must come BEFORE the subcommand for idea.py's parser
        cmd += ["--file", str(ledger)]
        cmd += list(args)
    else:
        cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ideas.md"
    path.write_text(LEDGER_HEADER)
    return path


@pytest.fixture
def ledger_with_rows(tmp_path: Path) -> Path:
    path = tmp_path / "ideas.md"
    path.write_text(
        LEDGER_HEADER
        + "| 2026-07-20 | 3 | Add dark mode | Enable dark mode in the UI | new | |\n"
        + "| 2026-07-21 | 4 | Fix auth bug | Auth token expires too quickly | accepted | 42 |\n"
        + "| 2026-07-22 | 2 | Minor typo fix | Fix typo on landing page | declined (test) | |\n"
    )
    return path


# --- capture ---


class TestCapture:
    def test_capture_returns_json(self, ledger):
        result = run("capture", "--title", "Test idea", "--desc", "Test description")
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["title"] == "Test idea"
        assert data["description"] == "Test description"

    def test_capture_empty_title_rejected(self, ledger):
        result = run("capture", "--title", "", "--desc", "desc")
        assert result.returncode != 0
        assert "ERROR" in result.stderr

    def test_capture_no_args_prompts(self, ledger):
        cmd = [sys.executable, str(IDEA_CMD), "--file", str(ledger), "capture"]
        result = subprocess.run(cmd, capture_output=True, text=True, input="Test\nDesc\n")
        assert result.returncode == 0, result.stderr
        # JSON is on the last line (prompts come before it)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        assert data["title"] == "Test"
        assert data["description"] == "Desc"


# --- dedupe ---


class TestDedupe:
    def test_dedupe_finds_ledger_match(self, ledger_with_rows):
        result = run("dedupe", "dark", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["count"] >= 1
        assert any(m["type"] == "ledger" and "dark" in m["title"] for m in data["matches"])

    def test_dedupe_finds_no_match(self, ledger_with_rows):
        result = run("dedupe", "xyzzy_nonexistent", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["count"] == 0

    def test_dedupe_case_insensitive(self, ledger_with_rows):
        result = run("dedupe", "DARK", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["count"] >= 1

    def test_dedupe_partial_word_match(self, ledger_with_rows):
        result = run("dedupe", "auth", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["count"] >= 1

    def test_dedupe_multiple_matches(self, ledger_with_rows):
        # "Fix" appears in two rows
        result = run("dedupe", "Fix", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["count"] >= 2

    def test_dedupe_empty_title(self):
        result = run("dedupe")
        # argparse rejects missing required 'title' arg (returncode 2)
        assert result.returncode != 0


# --- enrich ---


class TestEnrich:
    def test_enrich_updates_desire(self, ledger_with_rows):
        result = run("enrich", "--row", "1", "--desire", "5", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        # Verify the ledger was updated
        result2 = run_idea("list", ledger=ledger_with_rows)
        assert result2.returncode == 0
        assert "| 5 | Add dark mode" in result2.stdout

    def test_enrich_updates_notes(self, ledger_with_rows):
        result = run("enrich", "--row", "1", "--notes", "new detail", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr
        content = ledger_with_rows.read_text()
        assert "new detail" in content

    def test_enrich_by_title(self, ledger_with_rows):
        result = run("enrich", "--title", "Fix auth bug", "--desire", "3", ledger=ledger_with_rows)
        assert result.returncode == 0, result.stderr

    def test_enrich_row_out_of_range(self, ledger_with_rows):
        result = run("enrich", "--row", "99", "--desire", "3", ledger=ledger_with_rows)
        assert result.returncode != 0
        assert "out of range" in result.stderr

    def test_enrich_no_changes(self, ledger_with_rows):
        result = run("enrich", "--row", "1", ledger=ledger_with_rows)
        assert result.returncode == 0
        assert "no changes" in result.stdout.lower()

    def test_enrich_ambiguous_title(self, ledger_with_rows):
        # Add two rows with the same title
        ledger_with_rows.write_text(
            LEDGER_HEADER
            + "| 2026-07-20 | 3 | Duplicate | first | new | |\n"
            + "| 2026-07-21 | 3 | Duplicate | second | new | |\n"
        )
        result = run("enrich", "--title", "Duplicate", "--desire", "4", ledger=ledger_with_rows)
        assert result.returncode != 0
        assert "ambiguous" in result.stderr
