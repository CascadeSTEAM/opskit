"""Guard against injected `ansible_*` fact variables in our Ansible tree (issue #139).

ansible-core deprecated the injected fact variables (`ansible_hostname`,
`ansible_env.HOME`, ...) in favour of `ansible_facts["fact_name"]`; when
injection is removed they become hard failures on every play that touches
them. ansible-lint does not flag the pattern, so without this guard nothing
stops new instances from creeping back in after the #139 migration.

The check is an allowlist, not a blocklist: any `ansible_*` token in our
playbooks/roles/templates that is not a known magic or connection variable
fails the test. Nobody can enumerate every injected fact name, but the magic
and connection variables ARE a finite documented set — so an incomplete list
here produces a loud false positive (add the legit variable below), never a
silent miss. See SESSION-LOG 2026-08-05: a guard is only as good as its list.

Scope is `ansible/` only — vendored `ansible_collections/` are upstream's
problem and legitimately still use injected vars internally.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANSIBLE_TREE = ROOT / "ansible"

# Documented Ansible special variables (magic + connection/behavioral) that
# are NOT injected facts and remain valid indefinitely. Prefixes cover the
# families (ansible_ssh_*, ansible_become_*, ansible_loop_*).
ALLOWED = {
    "ansible_facts",
    "ansible_managed",
    "ansible_collections",
    # connection / behavioral
    "ansible_host",
    "ansible_port",
    "ansible_user",
    "ansible_password",
    "ansible_connection",
    "ansible_become",
    "ansible_python_interpreter",
    "ansible_shell_type",
    "ansible_shell_executable",
    # magic variables
    "ansible_check_mode",
    "ansible_diff_mode",
    "ansible_forks",
    "ansible_verbosity",
    "ansible_version",
    "ansible_index_var",
    "ansible_limit",
    "ansible_loop",
    "ansible_play_batch",
    "ansible_play_hosts",
    "ansible_play_hosts_all",
    "ansible_play_name",
    "ansible_play_role_names",
    "ansible_playbook_python",
    "ansible_role_name",
    "ansible_role_names",
    "ansible_collection_name",
    "ansible_config_file",
    "ansible_dependent_role_names",
    "ansible_inventory_sources",
    "ansible_parent_role_names",
    "ansible_parent_role_paths",
    "ansible_run_tags",
    "ansible_skip_tags",
}
ALLOWED_PREFIXES = ("ansible_ssh_", "ansible_become_", "ansible_loop_")

TOKEN = re.compile(r"\bansible_[a-z0-9_]+\b")

SCANNED_SUFFIXES = {".yml", ".yaml", ".j2"}


def _offenders():
    found = []
    for path in sorted(ANSIBLE_TREE.rglob("*")):
        if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for token in TOKEN.findall(line):
                if token in ALLOWED or token.startswith(ALLOWED_PREFIXES):
                    continue
                found.append(
                    f"{path.relative_to(ROOT)}:{lineno}: {token} in: {line.strip()}"
                )
    return found


def test_ansible_tree_exists():
    """If the tree moves, this guard must move with it — not silently scan nothing."""
    assert ANSIBLE_TREE.is_dir(), f"{ANSIBLE_TREE} is missing"
    assert any(ANSIBLE_TREE.rglob("*.yml")), "no YAML found under ansible/"


def test_no_injected_fact_vars():
    offenders = _offenders()
    assert not offenders, (
        "Injected ansible_* fact variable(s) found — use ansible_facts['name'] "
        "instead (deprecated by ansible-core, removal makes these hard "
        "failures). If a hit is a genuine magic/connection variable, add it to "
        "ALLOWED in this test:\n" + "\n".join(offenders)
    )
