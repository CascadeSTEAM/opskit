"""Static validation of ansible/playbooks/provision-compose-app-lxc.yml (#423).

A generic, parameterised cousin of provision-erpnext-dev-lxc.yml: an unprivileged
LXC that can run Docker, sized and addressed entirely from caller-supplied data.
It is never executed in CI (creating a container needs a live Proxmox node), so
the properties that matter are pinned here, following
tests/test_erpnext_dev_lxc_playbook.py.

Failure modes that are silent and expensive, one test each:

1. Adopting an occupied container ID.
2. Inventing an address, ID or hostname instead of requiring them.
3. Losing the Docker-in-LXC flags (nesting + keyctl).
4. Reporting a firewall that is not there: the firewall is an explicit choice,
   and the datacenter-firewall precondition applies only when it is chosen.
5. A dry run (--check) that shows nothing because its read-only discovery
   steps were skipped.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "provision-compose-app-lxc.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)

# Required from the caller. Giving any of these a default is the defect.
MUST_HAVE_NO_DEFAULT = ("ct_id", "ct_ip", "ct_gateway", "ct_hostname")


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def _flatten(tasks):
    out = []
    for task in tasks:
        out.append(task)
        out.extend(_flatten(task.get("block", [])))
    return out


def _with_guards(tasks, inherited=""):
    """(task, effective_guard): a task inside a block is also gated by the block's own `when`."""
    out = []
    for task in tasks:
        raw = task.get("when", "")
        if isinstance(raw, list):
            raw = " and ".join(str(r) for r in raw)
        guard = f"{inherited} {raw}".strip()
        out.append((task, guard))
        out.extend(_with_guards(task.get("block", []), guard))
    return out


def _task_named(fragment):
    hits = [t for t in _flatten(_tasks()) if fragment.lower() in str(t.get("name", "")).lower()]
    assert hits, f"no task whose name contains {fragment!r}"
    return hits[0]


def _cmd(task):
    for module in ("ansible.builtin.command", "ansible.builtin.shell"):
        if module in task:
            value = task[module]
            return value["cmd"] if isinstance(value, dict) else value
    return ""


def _create_task():
    hits = [t for t in _flatten(_tasks()) if "pct create" in _cmd(t)]
    assert len(hits) == 1, "exactly one task must run `pct create`"
    return hits[0]


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    assert not RFC1918.findall(PLAYBOOK.read_text()), "committed playbooks stay environment-agnostic (#134)"


def test_the_target_node_is_supplied_not_hardcoded():
    assert "target_host" in str(_play()["hosts"])


@pytest.mark.parametrize("var", MUST_HAVE_NO_DEFAULT)
def test_required_parameters_have_no_default(var):
    assert var not in (_play().get("vars") or {}), f"{var} must have no default: inventing one is the failure"


def test_required_parameters_are_asserted_before_anything_happens():
    asserts = [t for t in _flatten(_tasks()) if "ansible.builtin.assert" in t]
    text = " ".join(str(a["ansible.builtin.assert"]["that"]) for a in asserts)
    for var in MUST_HAVE_NO_DEFAULT:
        assert f"{var} is defined" in text, f"missing assert that {var} is defined"


def test_the_address_must_carry_a_prefix_length():
    text = " ".join(str(t.get("ansible.builtin.assert", "")) for t in _flatten(_tasks()))
    assert "'/' in ct_ip" in text


def test_an_occupied_id_is_refused_not_adopted():
    task = _task_named("Refuse to touch a container ID already used")
    that = " ".join(task["ansible.builtin.assert"]["that"])
    assert "hostname" in that and "ct_hostname" in that
    assert "existing_ct.rc == 0" in str(task.get("when"))


def test_creation_only_runs_when_the_container_is_absent():
    for fragment in ("pct create", "pveam download", "/etc/pve/firewall/{{ ct_id }}.fw <<"):
        for task, guard in _with_guards(_tasks()):
            if fragment in _cmd(task):
                assert "existing_ct.rc != 0" in guard, f"{fragment!r} must be gated on the container being absent"


def test_docker_in_lxc_flags_are_set():
    cmd = _cmd(_create_task())
    assert "nesting=1" in cmd
    assert "keyctl=1" in cmd


def test_unprivileged_by_default():
    assert _play()["vars"]["ct_unprivileged"] is True


def test_the_container_is_not_started_unless_asked():
    assert _play()["vars"]["ct_start_after_create"] is False
    start = _task_named("Start the container")
    assert "ct_start_after_create" in str(start.get("when"))


def test_onboot_is_a_variable_and_not_forced():
    assert "ct_onboot" in _play()["vars"]
    assert "ct_onboot" in _cmd(_create_task())


def test_name_resolution_flags_are_optional():
    cmd = _cmd(_create_task())
    assert "ct_nameserver" in cmd and "ct_searchdomain" in cmd
    for var in ("ct_nameserver", "ct_searchdomain"):
        assert _play()["vars"][var] == "", f"{var} must default to empty so the flag is omitted"


def test_the_firewall_is_an_explicit_choice():
    vars_ = _play()["vars"]
    assert vars_["ct_firewall"] is True, "default stays the safe one: firewalled"
    assert "require_datacenter_firewall" in vars_
    text = " ".join(str(t.get("ansible.builtin.assert", "")) for t in _flatten(_tasks()))
    assert "ct_firewall in [true, false, 'true', 'false', 'True', 'False']" in text, (
        "an unrecognised ct_firewall value must be refused, not read as false"
    )


def test_the_vnic_firewall_flag_follows_the_choice():
    cmd = _cmd(_create_task())
    assert "firewall=1" in cmd
    assert re.search(r"\{%-?\s*if\s+ct_firewall[^%]*%\}[^{]*firewall=1", cmd) or re.search(
        r"\{\{[^}]*ct_firewall[^}]*firewall=1", cmd
    ), "firewall=1 must be emitted only when ct_firewall is true"


def test_firewall_rules_and_datacenter_assertion_apply_only_when_chosen():
    for task, guard in _with_guards(_tasks()):
        name = str(task.get("name", ""))
        if "firewall rules file" in name.lower() or "datacenter firewall" in name.lower():
            assert "ct_firewall" in guard, f"{name!r} must only apply when ct_firewall is true"


def test_discovery_steps_run_in_check_mode_too():
    """Without check_mode: false a --check run skips these, existing_ct is never set, and the dry run shows nothing."""
    for fragment in ("Read the existing container config", "List templates already downloaded"):
        task = _task_named(fragment)
        assert task.get("check_mode") is False, f"{fragment!r} is read-only and must run under --check"
        assert task.get("changed_when") is False


def test_it_never_destroys_or_stops_anything():
    for task in _flatten(_tasks()):
        cmd = _cmd(task)
        for bad in ("pct destroy", "pct stop", "pct shutdown", "pct rollback", "qm destroy", "rm -rf"):
            assert bad not in cmd, f"{bad!r} has no place in a create-only play"


def test_the_report_states_the_firewall_outcome_honestly():
    text = str(_task_named("Report")["ansible.builtin.debug"])
    assert "NOT firewalled" in text, "a container created without a firewall must be reported as such"
    assert "ct_firewall" in text


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_playbook_passes_ansible_syntax_check():
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", "-i", "localhost,", "-e", "target_host=localhost", str(PLAYBOOK)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
