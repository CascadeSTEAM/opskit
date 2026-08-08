"""Static validation of ansible/playbooks/provision-proxmox-api-token.yml (#103).

Never executed in CI — issuing a token needs a live Proxmox node — so the
properties that matter are pinned here, per the precedent of
tests/test_mikrotik_provision_playbook.py.

The one that matters most is the **privsep intersection**. With `privsep=1`
the effective rights are the intersection of the token ACL and the user ACL.
Granted on the token only, reads succeed but listings come back as an empty
array rather than an error — indistinguishable from "there is nothing here".
A playbook that silently produced that half-working credential would be worse
than no playbook, so the dual grant is asserted here rather than trusted.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "provision-proxmox-api-token.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    out = []
    for task in _play()["tasks"]:
        out.append(task)
        out.extend(task.get("block", []))
    return out


def _commands():
    return [
        str(t[k].get("cmd", t[k]) if isinstance(t[k], dict) else t[k])
        for t in _tasks()
        for k in t
        if k == "ansible.builtin.command"
    ]


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    assert not RFC1918.search(PLAYBOOK.read_text())


def test_the_role_is_granted_to_both_the_user_and_the_token():
    """The privsep trap: a token-only grant reads as 'no results', not
    'denied'. Both grants, or the credential half-works silently."""
    commands = " ".join(_commands())

    assert "--users" in commands, "no user grant — listings will come back empty"
    assert "--tokens" in commands, "no token grant"


def test_the_token_is_created_with_privsep():
    assert any("--privsep 1" in c for c in _commands()), (
        "privsep=1 is the safer default and the reason for the dual grant"
    )


def test_both_grants_are_verified_before_success_is_reported():
    """Asserting the ACL read-back is what turns a silent half-grant into a
    loud failure."""
    asserts = [t for t in _tasks() if "ansible.builtin.assert" in t]
    verified = [
        t for t in asserts
        if "acl_list" in str(t["ansible.builtin.assert"].get("that", ""))
    ]
    assert verified, "nothing reads back the ACL to confirm both grants landed"


def test_the_scope_has_no_default():
    """A token's scope is the point of it; a default would be a guess."""
    assert "token_path" not in _play().get("vars", {})


def test_a_root_grant_requires_an_explicit_override():
    """Narrow-by-default must be structural, not remembered."""
    asserts = [
        str(t["ansible.builtin.assert"].get("that", ""))
        for t in _tasks() if "ansible.builtin.assert" in t
    ]
    guard = " ".join(asserts)

    assert "allow_root_grant" in guard
    assert "token_path != '/'" in guard


def test_the_default_role_is_read_only():
    assert _play()["vars"]["token_role"] == "PVEAuditor"
    assert _play()["vars"]["allow_root_grant"] is False


def test_creation_is_conditional_so_a_rerun_mints_nothing():
    """A token value is shown exactly once; a second token issued by a re-run
    would be an orphan nobody has the value for."""
    creates = [
        t for t in _tasks()
        if "ansible.builtin.command" in t and "token add" in str(t)
    ]
    assert creates, "no token-creation task found — did the play change shape?"
    for task in creates:
        assert task.get("when"), "token creation must be conditional"


def test_the_probes_never_fail_the_run():
    """Listing tokens for an account that has none is the normal first path."""
    for task in _tasks():
        cmd = str(task.get("ansible.builtin.command", ""))
        if "list" in cmd:
            assert task.get("changed_when") is False, (
                f"{task.get('name')!r} is a read but is not marked unchanged"
            )


def test_it_points_at_the_inventory_rather_than_ending_at_creation():
    """#103's whole point: issuing without tracking is the gap."""
    text = PLAYBOOK.read_text()
    assert "token-inventory.py" in text
