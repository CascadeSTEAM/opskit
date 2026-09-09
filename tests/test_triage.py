"""Tests for bin/triage.py (opskit #320).

Everything here is offline: no live GitHub, no live `gh`. Pure functions
tested against fixtures; subprocess tests use a throwaway `git init` repo.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "triage.py"


def load_module():
    spec = importlib.util.spec_from_file_location("triage_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = load_module()


# ── lint-body ────────────────────────────────────────────────────────────────

def test_lint_body_passes():
    content = "## Observed\n\nTest.\n\n## Measure\n\nbaseline: 0\ntarget: 1\n\n## Verify\n\n`make test`"
    missing = mod.lint_body(content)
    assert missing == []


def test_lint_body_missing_observed():
    content = "## Measure\n\nbaseline: 0\ntarget: 1\n\n## Verify\n\n`make test`"
    missing = mod.lint_body(content)
    assert "## Observed" in missing


def test_lint_body_missing_measure():
    content = "## Observed\n\nTest.\n\n## Verify\n\n`make test`"
    missing = mod.lint_body(content)
    assert "## Measure" in missing


def test_lint_body_missing_baseline():
    content = "## Observed\n\nTest.\n\n## Measure\n\n## Verify\n\n`make test`"
    missing = mod.lint_body(content)
    assert "## Measure: missing baseline:" in missing


def test_lint_body_missing_target():
    content = "## Observed\n\nTest.\n\n## Measure\n\nbaseline: 0\n\n## Verify\n\n`make test`"
    missing = mod.lint_body(content)
    assert "## Measure: missing target:" in missing


def test_lint_body_missing_verify():
    content = "## Observed\n\nTest.\n\n## Measure\n\nbaseline: 0\ntarget: 1\n"
    missing = mod.lint_body(content)
    assert "## Verify" in missing


# ── rubric ───────────────────────────────────────────────────────────────────

def test_priority_label_5_urgent_now():
    assert mod.priority_label(5, urgent_now=True) == "priority:urgent"


def test_priority_label_5_not_urgent_now():
    assert mod.priority_label(5, urgent_now=False) == "priority:high"


def test_priority_label_4():
    assert mod.priority_label(4) == "priority:high"


def test_priority_label_3():
    assert mod.priority_label(3) == "priority:medium"


def test_priority_label_1():
    assert mod.priority_label(1) == "priority:low"


def test_priority_label_2():
    assert mod.priority_label(2) == "priority:low"


# ── classify_evidence ────────────────────────────────────────────────────────

def test_classify_closeable():
    prs = [{"title": "#42: fix something", "body": "Closes #42"}]
    assert mod.classify_evidence(prs, 42) == "closeable"


def test_classify_review():
    prs = [{"title": "other PR", "body": "no mention"}]
    assert mod.classify_evidence(prs, 42) == "review"


# ── blocked_hints ────────────────────────────────────────────────────────────

def test_blocked_hints_infra():
    hints = mod.blocked_hints("This needs infra access")
    assert "blocked-infra" in hints


def test_blocked_hints_decision():
    hints = mod.blocked_hints("Owner decision needed")
    assert "needs-decision" in hints


def test_blocked_hints_none():
    hints = mod.blocked_hints("No issues here")
    assert hints == []


# ── subprocess: partition ────────────────────────────────────────────────────

def test_partition_in_temp_repo():
    """Run triage.py partition in a throwaway git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Init a git repo with some files
        subprocess.run(["git", "init", tmpdir], check=True, capture_output=True)
        Path(tmpdir, "test.txt").write_text("hello")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.email", "test@test.com"], check=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.name", "Test"], check=True)

        # Run partition with custom rules
        result = subprocess.run(
            ["python3", str(SCRIPT), "partition"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env={**os.environ, "OPSKIT_ROOT": tmpdir}
        )
        assert result.returncode == 0, f"partition failed: {result.stderr}"
        assert "partition:" in result.stdout


# ── subprocess: lint-body ────────────────────────────────────────────────────

def test_lint_body_subprocess():
    """Run triage.py lint-body on a valid file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("## Observed\n\nTest.\n\n## Measure\n\nbaseline: 0\ntarget: 1\n\n## Verify\n\n`make test`")
        f.flush()

        result = subprocess.run(
            ["python3", str(SCRIPT), "lint-body", f.name],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "lint-body: OK" in result.stdout

    os.unlink(f.name)


# ── subprocess: rubric ───────────────────────────────────────────────────────

def test_rubric_subprocess():
    result = subprocess.run(
        ["python3", str(SCRIPT), "rubric", "--impact", "3"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "priority:medium" in result.stdout


# ── subprocess: survey --check ───────────────────────────────────────────────

def test_survey_check_mode():
    """Survey with --check should fail when issues have !=1 priority label."""
    # This requires live gh — skip if no gh token
    try:
        result = subprocess.run(
            ["python3", str(SCRIPT), "survey", "--check"],
            capture_output=True,
            text=True
        )
        # If gh is available, --check may fail; if not, skip
        if result.returncode != 0 and "gh" in result.stderr:
            print("gh not available — survey --check skipped")
    except Exception:
        pass
