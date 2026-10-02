"""Static validation of ansible/playbooks/schedule-mail-auth-check.yml (#431).

Installs a weekly systemd USER timer that runs bin/mail-auth-check.py. Never executed in CI, so the properties that
matter are pinned here.

Failure modes that are silent and expensive, one test each:

1. Running on the wrong machine (connection=local means "whatever machine runs ansible").
2. A unit that points into a git worktree, which is deleted after the PR merges, so the check silently stops.
3. A timer that alerts every week on the same known problem, so the alert is ignored; it must fail only on regression.
4. A unit that can change DNS, or runs with more privilege than it needs.
5. A timer that silently misses a run while the machine was off (Persistent).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "schedule-mail-auth-check.yml"
EXAMPLE_CONFIG = ROOT / "environments" / "example" / "mail-domains.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def _text():
    return PLAYBOOK.read_text()


def _task_named(fragment):
    hits = [t for t in _tasks() if fragment.lower() in str(t.get("name", "")).lower()]
    assert hits, f"no task whose name contains {fragment!r}"
    return hits[0]


def _unit(name):
    task = _task_named(name)
    return task["ansible.builtin.copy"]["content"]


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    assert not RFC1918.findall(_text()), "committed playbooks stay environment-agnostic (#134)"


def test_it_targets_a_dedicated_inventory_group_not_every_host():
    assert _play()["hosts"] == "mail_auth_check_hosts"


def test_the_wrong_machine_is_refused_first():
    """Mandatory for every connection=local play (see workstation-maintenance.yml)."""
    first = _tasks()[0]
    assert "ansible.builtin.assert" in first
    assert "ansible_facts['hostname'] == inventory_hostname" in " ".join(str(c) for c in first["ansible.builtin.assert"]["that"])


def test_it_runs_unprivileged_because_the_units_are_per_user():
    assert _play().get("become") in (None, False)
    for task in _tasks():
        assert not task.get("become"), f"{task.get('name')!r} must not escalate: user units need no root"


def test_the_tool_and_the_configuration_must_exist_before_anything_is_installed():
    names = [str(t.get("name", "")).lower() for t in _tasks()]
    assert any("tool" in n and "exist" in n for n in names)
    assert any("configuration" in n and "exist" in n for n in names)
    assert any("dig" in n for n in names), "the checker needs dig; fail early with a clear message"


def test_the_root_defaults_to_the_primary_checkout_never_a_worktree():
    """A worktree is deleted after the PR merges; a unit pointing into it would silently stop working."""
    variables = _play()["vars"]
    assert "mail_auth_root" in variables
    assert "wt" not in str(variables["mail_auth_root"]).lower()
    assert "playbook_dir" not in str(variables["mail_auth_root"]), "the playbook may run from a worktree"
    assert any("worktree" in str(t.get("name", "")).lower() for t in _tasks()), "refuse a root that is a worktree"


def test_the_service_runs_the_tool_read_only_and_alerts_only_on_regression():
    service = _unit("service unit")
    assert "Type=oneshot" in service
    assert "bin/mail-auth-check.py" in service
    assert "--fail-on regression" in service
    assert "--save" in service
    for forbidden in ("--no-save", "sudo", "nsupdate", "curl", "wget"):
        assert forbidden not in service


def test_the_timer_is_weekly_and_catches_up_after_downtime():
    timer = _unit("timer unit")
    assert re.search(r"^OnCalendar=", timer, re.M)
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "RandomizedDelaySec" in timer, "do not hit public resolvers on the minute"


def test_the_units_are_installed_per_user_and_enabled_in_the_user_manager():
    text = _text()
    assert ".config/systemd/user" in text
    systemd_tasks = [t for t in _tasks() if "ansible.builtin.systemd" in t]
    assert systemd_tasks, "enable the timer through the systemd module"
    for task in systemd_tasks:
        assert task["ansible.builtin.systemd"].get("scope") == "user"


def test_the_user_manager_bus_is_reachable_from_a_non_login_shell():
    assert "XDG_RUNTIME_DIR" in _text()


def test_it_never_changes_dns_or_touches_secrets():
    text = _text().lower()
    for bad in ("api.cloudflare", "dns_records", "nsupdate", "bw ", "bitwarden", "password", "token"):
        assert bad not in text, f"{bad!r} has no place in a read-only scheduler"


def test_the_report_says_how_to_look_and_what_is_not_done():
    report = str(_task_named("Report")["ansible.builtin.debug"])
    for hint in ("list-timers", "--failed", "--status"):
        assert hint in report
    assert "linger" in report.lower() and "not" in report.lower()


def test_check_mode_is_safe_nothing_runs_the_tool_for_real():
    for task in _tasks():
        cmd = str(task.get("ansible.builtin.command", "")) + str(task.get("ansible.builtin.shell", ""))
        assert "mail-auth-check.py" not in cmd or task.get("check_mode") is False or "--help" in cmd


def test_the_example_configuration_is_valid_for_the_tool():
    """The documented schema and the validator must not drift apart."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("mail_auth_check", ROOT / "bin" / "mail-auth-check.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["mail_auth_check"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    specs = module.load_config(EXAMPLE_CONFIG.read_text())
    assert specs and all(s.name.endswith((".example", ".example.com", "example.com", "example.org")) for s in specs)


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_playbook_passes_ansible_syntax_check():
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", "-i", "localhost,", str(PLAYBOOK)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr



def test_the_interpreter_the_unit_will_use_must_be_able_to_import_pyyaml():
    """The service runs /usr/bin/python3 and the tool imports yaml; without this check the first scheduled run fails with an
    ImportError nobody expected."""
    names = [str(t.get("name", "")).lower() for t in _tasks()]
    index = next(i for i, n in enumerate(names) if "pyyaml" in n)
    check = _tasks()[index]
    command = str(check.get("ansible.builtin.command", ""))
    assert "/usr/bin/python3" in command and "import yaml" in command
    assert check.get("changed_when") is False and check.get("check_mode") is False
    unit_index = next(i for i, n in enumerate(names) if "service unit" in n)
    assert index < unit_index, "check before anything is installed"
    assert "/usr/bin/python3" in _unit("service unit"), "the checked interpreter must be the one the unit runs"


def test_every_unit_is_named_per_environment_so_environments_do_not_overwrite_each_other():
    """#433: with one fixed name, scheduling a second environment on the same host replaced the first one's schedule."""
    unit = "mail-auth-check-{{ mail_auth_env }}"
    assert _task_named("service unit")["ansible.builtin.copy"]["dest"].endswith(f"{unit}.service")
    assert _task_named("timer unit")["ansible.builtin.copy"]["dest"].endswith(f"{unit}.timer")
    assert f"Unit={unit}.service" in _unit("timer unit")
    enable = next(t for t in _tasks() if "ansible.builtin.systemd" in t)
    assert enable["ansible.builtin.systemd"]["name"] == f"{unit}.timer"


def test_the_bare_unqualified_unit_names_are_gone():
    text = _text()
    assert not re.search(r"mail-auth-check\.(service|timer)", text), "a fixed name would collide between environments"


def test_the_report_shows_the_per_environment_commands():
    report = str(_task_named("Report")["ansible.builtin.debug"])
    assert "mail-auth-check-" in report and "list-timers" in report
