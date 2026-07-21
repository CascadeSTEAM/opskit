"""Tests for bin/publication-guard.sh token matching (issue #31).

The content check always used word boundaries; the path check didn't,
so a short token whose letters appear inside "docs/" matched every docs path.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "bin" / "publication-guard.sh"


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=tmp_path, check=True, capture_output=True,
        )
    git("init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("hello\n")
    git("add", "README.md")
    git("commit", "-q", "-m", "init")
    return tmp_path


def run_guard(repo_dir, token="oc"):
    return subprocess.run(
        ["bash", str(GUARD), "--cached"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": token,
             "OPSKIT_ROOT": str(repo_dir)},
    )


def stage(repo_dir, relpath, content="clean line\n"):
    p = repo_dir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    subprocess.run(["git", "add", relpath], cwd=repo_dir, check=True, capture_output=True)


def test_short_token_does_not_match_inside_path_words(repo):
    # a short token must not match its letters inside the word "docs/"
    stage(repo, "docs/notes.md")
    result = run_guard(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_token_as_path_segment_is_caught(repo):
    stage(repo, "oc/notes.md")
    result = run_guard(repo)
    assert result.returncode == 1
    assert "client token 'oc'" in result.stdout


def test_token_in_hyphenated_filename_is_caught(repo):
    stage(repo, "notes/oc-facts.md")
    result = run_guard(repo)
    assert result.returncode == 1


def test_token_in_content_is_caught(repo):
    stage(repo, "docs/notes.md", "the oc network\n")
    result = run_guard(repo)
    assert result.returncode == 1
    assert "content line" in result.stdout


def test_compound_word_in_content_passes(repo):
    stage(repo, "docs/notes.md", "see docs for details\n")
    result = run_guard(repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_override_allows_reviewed_commit(repo):
    stage(repo, "oc/notes.md")
    result = subprocess.run(
        ["bash", str(GUARD), "--cached"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLIENT_TOKENS": "oc",
             "ALLOW_CLIENT_TOKENS": "1", "OPSKIT_ROOT": str(repo)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
