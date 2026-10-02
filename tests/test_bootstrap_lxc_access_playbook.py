"""Static validation of ansible/playbooks/bootstrap-lxc-access.yml (#425).

Gives a freshly created, stopped LXC an SSH server and key-only root access, entirely
through `pct` on the Proxmox node (the container has no SSH to connect to yet). It is never
executed in CI, so the properties that matter are pinned here, following
tests/test_erpnext_dev_lxc_playbook.py and tests/test_compose_app_lxc_playbook.py.

Failure modes that are silent and expensive, one test each:

1. Opening password login, or root login with a password, on a container that is about to be
   reachable from the network.
2. Authorizing something that is not a public key (a private key, a path, a typo) and so
   locking everyone out or leaking a secret into the container.
3. Enabling an sshd whose config does not parse.
4. Acting on a container the caller did not name, or destroying/stopping one.
5. A dry run (--check) that shows nothing because its read-only discovery was skipped.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "bootstrap-lxc-access.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)

MUST_HAVE_NO_DEFAULT = ("ct_id", "ct_authorized_keys")


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


def _text():
    return PLAYBOOK.read_text()


def _task_named(fragment):
    tasks = _flatten(_tasks())
    exact = [t for t in tasks if str(t.get("name", "")) == fragment]
    if exact:
        return exact[0]
    hits = [t for t in tasks if fragment.lower() in str(t.get("name", "")).lower()]
    assert hits, f"no task whose name contains {fragment!r}"
    return hits[0]


def _cmd(task):
    for module in ("ansible.builtin.command", "ansible.builtin.shell"):
        if module in task:
            value = task[module]
            if isinstance(value, dict):
                return value.get("cmd") or " ".join(str(a) for a in value.get("argv", []))
            return value
    return ""


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    assert not RFC1918.findall(_text()), "committed playbooks stay environment-agnostic (#134)"


def test_the_target_node_is_supplied_not_hardcoded():
    assert "target_host" in str(_play()["hosts"])


@pytest.mark.parametrize("var", MUST_HAVE_NO_DEFAULT)
def test_required_parameters_have_no_default(var):
    assert var not in (_play().get("vars") or {}), f"{var} must have no default"


def test_required_parameters_are_asserted_first():
    first = _tasks()[0]
    assert "ansible.builtin.assert" in first
    that = " ".join(str(c) for c in first["ansible.builtin.assert"]["that"])
    for var in MUST_HAVE_NO_DEFAULT:
        assert f"{var} is defined" in that


def test_only_public_keys_are_accepted():
    """A private key or a path pasted by mistake must be refused before anything is written."""
    text = " ".join(str(t.get("ansible.builtin.assert", "")) for t in _flatten(_tasks()))
    assert "ct_authorized_keys | length > 0" in text
    assert "PRIVATE KEY" in text, "an explicit refusal of private key material"
    assert re.search(r"(ssh-ed25519|ssh-rsa|sk-|ecdsa-sha2)", text), "keys are checked for a public-key prefix"


def test_ssh_is_key_only_and_root_has_no_password_login():
    text = _text()
    assert "PermitRootLogin prohibit-password" in text
    assert "PasswordAuthentication no" in text
    assert "KbdInteractiveAuthentication no" in text
    assert "PermitRootLogin yes" not in text
    assert "PasswordAuthentication yes" not in text
    for bad in ("passwd ", "chpasswd", "usermod -p"):
        assert bad not in text, f"{bad!r}: this play must never set a password"


def test_the_sshd_config_is_validated_before_ssh_is_enabled():
    names = [str(t.get("name", "")) for t in _flatten(_tasks())]
    validate = next(i for i, n in enumerate(names) if "validate" in n.lower() and "sshd" in n.lower())
    enable = next(i for i, n in enumerate(names) if "enable" in n.lower() and "ssh" in n.lower())
    assert validate < enable
    assert "sshd -t" in _cmd(_flatten(_tasks())[validate])


def test_everything_goes_through_pct_on_the_node():
    for fragment in ("Install", "authorized"):
        task = _task_named(fragment)
        assert "pct exec" in _cmd(task) or "pct" in str(task), f"{fragment!r} must act through pct exec"


def test_the_container_must_exist_and_is_only_started_if_stopped():
    assert "pct config" in _cmd(_task_named("Read the container config"))
    assert "rc == 0" in " ".join(str(c) for c in _task_named("Refuse to act on a container that does not exist")["ansible.builtin.assert"]["that"])
    start = _task_named("Start the container")
    assert "pct start" in _cmd(start)
    assert "stopped" in str(start.get("when")), "start only a stopped container"


def test_it_never_destroys_stops_or_resets_anything():
    for task in _flatten(_tasks()):
        cmd = _cmd(task)
        for bad in ("pct destroy", "pct stop", "pct shutdown", "pct rollback", "pct restore", "pct resize", "rm -rf", "mkfs"):
            assert bad not in cmd, f"{bad!r} has no place in a bootstrap play"


def test_discovery_steps_run_in_check_mode_too():
    for fragment in ("Read the container config", "Read the container status"):
        task = _task_named(fragment)
        assert task.get("check_mode") is False, f"{fragment!r} is read-only and must run under --check"
        assert task.get("changed_when") is False


def test_authorizing_a_key_is_idempotent():
    task = _task_named("Authorize")
    cmd = _cmd(task)
    assert "grep -qxF" in cmd, "append a key only when it is not already present"
    assert "authorized_keys" in cmd
    assert "chmod 600" in cmd or "install -m 600" in cmd or "umask 077" in cmd


def test_the_report_says_how_to_connect_and_what_was_not_done():
    text = str(_task_named("Report")["ansible.builtin.debug"])
    assert "ssh" in text.lower()
    assert "not" in text.lower()


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="ansible-playbook not installed")
def test_playbook_passes_ansible_syntax_check():
    result = subprocess.run(
        ["ansible-playbook", "--syntax-check", "-i", "localhost,", "-e", "target_host=localhost", str(PLAYBOOK)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
