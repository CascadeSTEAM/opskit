"""Guards for the lifecycle-service playbook's repo-path references (issue #143).

Three times now a lifecycle-service path pointed at something that does not
exist in this repository (#84, #95, #143): `scripts/lifecycle-processor.py`
and `requirements.txt` both survived review because nothing executes the
playbook in CI — a phantom path fails only at cutover time, on the operator's
machine. These tests resolve every `{{ repo_root }}/...` reference in the
playbook and its unit template against the actual repo, so the class dies
here instead of recurring a fourth time.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "restart-lifecycle-service.yml"
UNIT_TEMPLATE = (
    ROOT / "ansible" / "playbooks" / "templates" / "lifecycle-processor.service.j2"
)

# {{ repo_root }}/some/path — capture up to whitespace, quote, or next Jinja.
REPO_PATH = re.compile(r"\{\{\s*repo_root\s*\}\}/([^\s\"'{}]+)")


def _repo_paths(text: str) -> set[str]:
    # Comment lines are history, not references — the playbook documents the
    # old phantom paths (#95) in prose, which must not re-trip the guard.
    live = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    return set(REPO_PATH.findall(live))


def _referenced_paths() -> set[str]:
    paths = _repo_paths(PLAYBOOK.read_text())
    paths |= _repo_paths(UNIT_TEMPLATE.read_text())
    # venv_python is {{ repo_root }}/.venv/... via a var; .venv is built at
    # deploy time and gitignored, so only non-venv paths must exist in git.
    return {p for p in paths if not p.startswith(".venv")}


def test_playbook_and_template_exist():
    assert PLAYBOOK.is_file()
    assert UNIT_TEMPLATE.is_file()


def test_repo_paths_are_found():
    """The extraction itself must not silently go hollow."""
    assert _referenced_paths(), (
        "no {{ repo_root }}/... references found — the regex or the playbook "
        "changed shape and this guard is no longer checking anything"
    )


def test_all_repo_path_references_exist():
    missing = sorted(p for p in _referenced_paths() if not (ROOT / p).exists())
    assert not missing, (
        f"playbook/unit reference repo paths that do not exist: {missing} — "
        "this is the #84/#95/#143 phantom-path defect again"
    )


def test_watch_dirs_exist():
    """The unit's ExecStart runs --watch; the processor only schedules
    watchers for directories that exist, so a missing dir is silently
    never watched rather than an error."""
    for d in ("proposals", "plans"):
        assert (ROOT / d).is_dir(), f"{d}/ watch directory missing"


def test_watchdog_dependency_declared():
    """--watch imports watchdog at runtime; a venv built from the
    requirements file without it crash-loops the service."""
    reqs = (ROOT / "requirements-dev.txt").read_text()
    assert re.search(r"^watchdog\b", reqs, re.MULTILINE), (
        "watchdog missing from requirements-dev.txt — the systemd unit's "
        "--watch mode cannot start"
    )


def test_unit_execstart_uses_bin_copy():
    """The exact #143 regression: the unit must execute this repo's
    bin/lifecycle-processor.py, never a scripts/ path or sibling checkout."""
    text = UNIT_TEMPLATE.read_text()
    assert "bin/lifecycle-processor.py" in text
    assert "scripts/lifecycle-processor.py" not in PLAYBOOK.read_text()
