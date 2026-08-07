"""Tests for bin/secret-scan.sh — the shared grep-based secret gate (issue #157).

The hook and CI used to define their own pattern lists, and CI's was strictly
stricter (`secret`, `token`, and `[:=]` rather than `=`). So a commit could pass
every local gate and fail only in CI — the exact round-trip the hook's own
comment claimed to prevent. These tests pin the collapse to one source, and the
structural property that matters: neither caller may carry its own patterns
again, because a comment claiming "shared with CI" is what failed last time.
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ROOT / "bin" / "secret-scan.sh"
HOOK = ROOT / ".githooks" / "pre-commit"
CI = ROOT / ".github" / "workflows" / "ci.yml"


# Fixtures are COMPOSED AT RUNTIME, never written as literals. The scan under
# test would otherwise flag this very file, and the alternative — allowlisting
# the test path — would weaken the gate to accommodate its own tests. Same
# lesson as the token-suggester in #135: writing about a guard is as leak-prone
# as writing around one.
FAKE = "h4ckme" + "notreal" + "value"          # long enough to trip the {8,} bound
Q = chr(34)


def _pair(keyword: str, sep: str = ":") -> str:
    """`<keyword><sep> "<fake value>"` — assembled so no literal appears here."""
    return keyword + sep + " " + Q + FAKE + Q


def _private_key_header() -> str:
    return "-----BEGIN " + "RSA" + " PRIVATE KEY" + "-----"


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    return tmp_path


def _run(repo: Path, *args: str, **env_extra):
    env = {**os.environ, "OPSKIT_ROOT": str(repo), **env_extra}
    return subprocess.run(["bash", str(SCAN), *args], env=env,
                          capture_output=True, text=True, cwd=str(repo))


def _stage(repo: Path, name: str, content: str):
    (repo / name).write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)


# ── the drift itself ─────────────────────────────────────────────────────

# The patterns CI had and the hook did not: these are the regression.
CI_ONLY = [
    ("secret with a colon", _pair("my_secret")),
    ("token with a colon", _pair("auth_token")),
    ("secret with equals", _pair("my_secret", " =")),
    ("token with equals", _pair("api_token", " =")),
]


def test_ci_only_patterns_now_fail_locally(tmp_path):
    """Each of these passed the old hook and failed CI. All must now fail
    at the staged gate, before a push."""
    for label, line in CI_ONLY:
        repo = _repo(tmp_path / label.replace(" ", "_"))
        _stage(repo, "config.yml", line + "\n")
        result = _run(repo, "--cached")
        assert result.returncode == 1, f"{label!r} did not trip the gate"
        assert "possible secret detected" in result.stderr


def test_patterns_the_hook_already_had_still_fail(tmp_path):
    """Collapsing to one list must not loosen the local gate either."""
    cases = [
        _pair("password", " ="),
        _pair("api_key", " ="),
        _private_key_header(),
        "ghp_" + "a" * 36,
        "AIza" + "b" * 35,
    ]
    for i, line in enumerate(cases):
        repo = _repo(tmp_path / f"had{i}")
        _stage(repo, "config.yml", line + "\n")
        assert _run(repo, "--cached").returncode == 1, f"{line[:20]!r} not caught"


def test_jinja_placeholder_is_not_a_secret(tmp_path):
    """The `[^{]` guard: a false positive only the local gate produced is how
    people learn to reach for --no-verify."""
    repo = _repo(tmp_path / "jinja")
    _stage(repo, "role.yml", "password: " + Q + "{{ vault_password }}" + Q + "\n")
    assert _run(repo, "--cached").returncode == 0


def test_clean_staged_content_passes(tmp_path):
    repo = _repo(tmp_path / "clean")
    _stage(repo, "notes.md", "nothing to see\n")
    assert _run(repo, "--cached").returncode == 0


# ── scope of each mode ───────────────────────────────────────────────────


def test_cached_mode_checks_files_of_any_extension(tmp_path):
    """A secret committed as an extensionless file is still published."""
    repo = _repo(tmp_path / "noext")
    _stage(repo, "config.local", _pair("token") + "\n")
    assert _run(repo, "--cached").returncode == 1


def test_cached_mode_ignores_unstaged_worktree_noise(tmp_path):
    """What is about to be committed is what must be clean."""
    repo = _repo(tmp_path / "unstaged")
    _stage(repo, "ok.md", "fine\n")
    (repo / "scratch.yml").write_text(_pair("token") + "\n")  # not staged
    assert _run(repo, "--cached").returncode == 0


def test_tree_mode_scans_tracked_files_only(tmp_path):
    """A publication gate's remit is tracked content. Walking the filesystem
    would read the gitignored environments/ layer, which holds REAL client
    credentials — printing those to warn about secrets would be the leak the
    scan exists to prevent."""
    repo = _repo(tmp_path / "tree")
    _stage(repo, "ok.yml", "clean: true\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    (repo / ".gitignore").write_text("private/\n")
    (repo / "private").mkdir()
    (repo / "private" / "real.yml").write_text(_pair("password") + "\n")

    result = _run(repo, "--tree")

    assert result.returncode == 0, result.stderr
    assert FAKE not in result.stdout + result.stderr


def test_tree_mode_catches_a_committed_secret(tmp_path):
    repo = _repo(tmp_path / "tree_bad")
    _stage(repo, "bad.yml", _pair("api_key") + "\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    assert _run(repo, "--tree").returncode == 1


def test_override_is_available_but_explicit(tmp_path):
    repo = _repo(tmp_path / "override")
    _stage(repo, "config.yml", _pair("token") + "\n")
    assert _run(repo, "--cached", ALLOW_SECRET_SCAN="1").returncode == 0


def test_bad_mode_is_rejected(tmp_path):
    repo = _repo(tmp_path / "badmode")
    assert _run(repo, "--nonsense").returncode == 2


# ── the structural guarantee ─────────────────────────────────────────────


def test_both_gates_call_the_shared_script():
    assert "bin/secret-scan.sh --cached" in HOOK.read_text()
    assert "bin/secret-scan.sh --tree" in CI.read_text()


def test_neither_gate_carries_its_own_patterns():
    """The defect was two lists, not one wrong list. A caller that inlines a
    keyword pattern again can drift again, whatever its comments claim."""
    for path in (HOOK, CI):
        text = path.read_text()
        for keyword in ("password", "api[_-]?key", "api_key", "ghp_", "AIza"):
            assert f'{keyword}\\s*' not in text, (
                f"{path.name} inlines a secret pattern for {keyword!r} — "
                "patterns belong only in bin/secret-scan.sh"
            )


def test_patterns_are_introspectable():
    """--print-patterns exists so a test can assert on the real list rather
    than a copy of it that can itself drift."""
    out = subprocess.run(["bash", str(SCAN), "--print-patterns"],
                         capture_output=True, text=True, check=True).stdout
    patterns = [p for p in out.splitlines() if p.strip()]
    assert len(patterns) >= 4
    joined = "\n".join(patterns)
    for keyword in ("password", "secret", "token", "api", "PRIVATE KEY"):
        assert keyword in joined
