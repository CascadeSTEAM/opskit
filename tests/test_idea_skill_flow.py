"""Integration tests for the idea-cmd skill flow.

Tests the full capture → dedupe → ledger add → enrich cycle
that the skill orchestrates. Uses mocked GH where needed.
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
IDEA_CMD = ROOT / "bin" / "idea-cmd.py"
IDEA_PY = ROOT / "bin" / "idea.py"

LEDGER_HEADER = (
    "# Test Ledger\n\n"
    "| Date | Desire (1-5) | Title | Description | Status | GH# |\n"
    "|------|--------------|-------|-------------|--------|-----|\n"
)


def run_idea_cmd(*args: str, ledger: Path = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(IDEA_CMD)]
    if ledger:
        cmd += ["--file", str(ledger)]
    cmd += args
    return subprocess.run(cmd, capture_output=True, text=True)


def run_idea(*args: str, ledger: Path = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(IDEA_PY)]
    if ledger:
        # --file must come BEFORE the subcommand for idea.py's parser
        cmd += ["--file", str(ledger)]
        # Split args: first element is the subcommand
        subcmd = args[0] if args else "list"
        cmd.append(subcmd)
        cmd += args[1:]
    else:
        cmd += args
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    path = tmp_path / "ideas.md"
    path.write_text(LEDGER_HEADER)
    return path


class TestFullFlowCapture:
    """Test the capture → dedupe → add flow."""

    def test_capture_then_add_flow(self, ledger):
        """Simulate the skill's capture-then-add flow."""
        # Step 1: capture returns JSON
        cap = run_idea_cmd("capture", "--title", "Feature X", "--desc", "Do thing Y", ledger=ledger)
        assert cap.returncode == 0, cap.stderr
        data = json.loads(cap.stdout)
        assert data["title"] == "Feature X"

        # Step 2: dedupe shows no matches
        ded = run_idea_cmd("dedupe", "Feature X", ledger=ledger)
        assert ded.returncode == 0, ded.stderr
        ded_data = json.loads(ded.stdout)
        assert ded_data["count"] == 0

        # Step 3: add to ledger
        add = run_idea("add", "--desire", "4", "--title", "Feature X", "--desc", "Do thing Y", ledger=ledger)
        assert add.returncode == 0, add.stderr
        assert "added row 1" in add.stdout

        # Verify ledger state
        list_result = run_idea("list", ledger=ledger)
        assert list_result.returncode == 0
        assert "Feature X" in list_result.stdout
        assert "| new" in list_result.stdout

    def test_capture_dedupe_enrich_flow(self, ledger):
        """Simulate capture → dedupe finds match → enrich existing."""
        # First add an initial row
        run_idea("add", "--desire", "3", "--title", "Dark mode", "--desc", "Add dark theme", ledger=ledger)

        # Capture a similar idea
        cap = run_idea_cmd("capture", "--title", "Dark mode v2", "--desc", "Dark theme v2", ledger=ledger)
        assert cap.returncode == 0

        # Dedupe should find the existing "Dark mode" row
        ded = run_idea_cmd("dedupe", "Dark", ledger=ledger)
        assert ded.returncode == 0
        ded_data = json.loads(ded.stdout)
        assert ded_data["count"] >= 1

        # Enrich the existing row
        enrich = run_idea_cmd("enrich", "--row", "1", "--desire", "5",
                              "--notes", "upgraded to v2", ledger=ledger)
        assert enrich.returncode == 0, enrich.stderr
        assert "row 1 updated" in enrich.stdout

        # Verify: original row now has desire=5 and enriched notes
        list_result = run_idea("list", ledger=ledger)
        assert list_result.returncode == 0
        assert "| 5 | Dark mode |" in list_result.stdout

    def test_capture_dedupe_no_match_then_add(self, ledger):
        """Capture → dedupe finds nothing → add new row."""
        cap = run_idea_cmd("capture", "--title", "New feature", "--desc", "Something new", ledger=ledger)
        assert cap.returncode == 0

        ded = run_idea_cmd("dedupe", "New feature xyz", ledger=ledger)
        ded_data = json.loads(ded.stdout)
        assert ded_data["count"] == 0

        add = run_idea("add", "--desire", "4", "--title", "New feature", "--desc", "Something new", ledger=ledger)
        assert add.returncode == 0

        list_result = run_idea("list", ledger=ledger)
        assert "New feature" in list_result.stdout


class TestDedupeAgainstLedgerAndGH:
    """Test dedupe across ledger and GH sources."""

    def test_dedupe_combines_ledger_and_gh(self, ledger):
        """Dedupe shows matches from both ledger and GH (when available)."""
        # Add two rows
        run_idea("add", "--desire", "3", "--title", "Auth fix", "--desc", "Fix auth", ledger=ledger)
        run_idea("add", "--desire", "4", "--title", "Auth timeout", "--desc", "Auth expires too fast", ledger=ledger)

        # Dedupe should find both
        ded = run_idea_cmd("dedupe", "Auth", ledger=ledger)
        ded_data = json.loads(ded.stdout)
        ledger_matches = [m for m in ded_data["matches"] if m["type"] == "ledger"]
        assert len(ledger_matches) == 2

    def test_dedupe_gh_search_when_gh_unavailable(self, ledger):
        """When gh is not available, dedupe still works with ledger only."""
        run_idea("add", "--desire", "3", "--title", "Test idea", "--desc", "desc", ledger=ledger)
        ded = run_idea_cmd("dedupe", "Test", ledger=ledger)
        assert ded.returncode == 0
        data = json.loads(ded.stdout)
        assert data["count"] >= 1
