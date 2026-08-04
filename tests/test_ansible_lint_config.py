"""Tests for .ansible-lint.yml — that ansible-lint can actually run (issue #83).

`skip_list` used to contain `syntax-check[specific]`. That rule is unskippable,
so listing it makes ansible-lint refuse to run *at all* rather than skip that
one rule: it exits non-zero with a config error before evaluating a single
rule. For as long as the entry was present, no playbook or role in this repo
was ever linted.

The failure mode is what makes it worth a guard. A non-zero exit reads as "lint
ran and found problems", not "lint never ran", so the breakage survived in both
the local config and the CI invocation without anyone noticing.

These tests pin the two halves: the config must never list an unskippable rule,
and ansible-lint must genuinely evaluate rules when pointed at the repo config.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".ansible-lint.yml"

# Rules tagged `unskippable` in ansible-lint. Listing any of these — bare or as
# a sub-rule like `syntax-check[specific]` — is a hard config error, not a skip.
UNSKIPPABLE = {"syntax-check", "load-failure"}


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text()) or {}


def _base_rule(entry: str) -> str:
    """`syntax-check[specific]` -> `syntax-check`; leaves bare ids untouched."""
    return entry.split("[", 1)[0].strip()


def test_config_exists_and_parses():
    assert CONFIG.is_file(), f"{CONFIG} is missing"
    assert isinstance(_config(), dict)


@pytest.mark.parametrize("key", ["skip_list", "warn_list"])
def test_no_unskippable_rules_listed(key):
    """The exact regression: an unskippable rule in skip_list/warn_list."""
    listed = _config().get(key) or []
    offenders = [e for e in listed if _base_rule(str(e)) in UNSKIPPABLE]
    assert not offenders, (
        f"{key} contains unskippable rule(s) {offenders} — ansible-lint will "
        f"refuse to run at all and lint nothing. Use exclude_paths for a file "
        f"that genuinely cannot pass."
    )


def test_environments_layer_excluded():
    """Local env data is gitignored and absent in CI; linting it locally would
    make `make lint` disagree with CI (issue #19)."""
    excluded = [str(p).rstrip("/") for p in (_config().get("exclude_paths") or [])]
    assert "environments" in excluded, (
        "exclude_paths should exclude environments/ so local runs match CI"
    )


@pytest.mark.skipif(
    shutil.which("ansible-lint") is None, reason="ansible-lint not installed"
)
def test_ansible_lint_actually_runs(tmp_path):
    """Behavioural half: with this repo's config, ansible-lint must evaluate
    rules rather than abort on the config itself."""
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        "---\n"
        "- name: Minimal valid play\n"
        "  hosts: localhost\n"
        "  gather_facts: false\n"
        "  tasks:\n"
        "    - name: Do nothing\n"
        "      ansible.builtin.debug:\n"
        "        msg: ok\n"
    )
    result = subprocess.run(
        ["ansible-lint", "-c", str(CONFIG), "--offline", str(playbook)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    combined = result.stdout + result.stderr
    assert "is unskippable" not in combined, (
        f"ansible-lint aborted on the config instead of linting:\n{combined}"
    )
    assert result.returncode == 0, (
        f"a minimal valid playbook should pass this config:\n{combined}"
    )


def test_ci_ansible_lint_step_is_blocking():
    """#87 made the CI ansible-lint step enforcing. `continue-on-error: true` is
    how it hid a totally broken invocation for months (#83) — if it comes back,
    the gate is decorative again and nobody will notice."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    start = ci.index("- name: ansible-lint")
    # the step ends at the next step at the same indentation
    rest = ci[start:]
    end = rest.find("\n      - name:", 1)
    step = rest if end == -1 else rest[:end]
    assert "continue-on-error" not in step, (
        "the ansible-lint CI step must stay blocking — tracked ansible/ has zero "
        "failures and every remaining finding is a deliberate warn_list entry"
    )


def test_warn_list_entries_are_not_silent_skips():
    """A rule in warn_list is a judged decision; one in skip_list disappears
    entirely. Nothing this repo judged should be silently skipped instead."""
    cfg = _config()
    warn = {str(e) for e in (cfg.get("warn_list") or [])}
    skip = {str(e) for e in (cfg.get("skip_list") or [])}
    assert not (warn & skip), f"rules in both warn_list and skip_list: {warn & skip}"
    # the decisions #87 recorded, which should not quietly become skips
    for rule in ("yaml[line-length]", "var-naming[no-role-prefix]", "args[module]"):
        assert rule not in skip, f"{rule} was judged as a warning, not a skip"
