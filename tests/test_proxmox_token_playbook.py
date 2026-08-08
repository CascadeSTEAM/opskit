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

import json
import re
from pathlib import Path

import pytest
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
        if "acl_ugids" in str(t["ansible.builtin.assert"].get("that", ""))
    ]
    assert verified, "nothing reads back the ACL to confirm both grants landed"


# ── the conditions are evaluated, not just grepped for (#103 review) ─────────
# The first version of these tests only checked that certain substrings
# appeared in the playbook source. That could not distinguish a correct
# condition from a broken one — and did not, in fact, catch the substring
# collisions below. These render the real Jinja against realistic fixtures.

import jinja2  # a declared test dependency: a skipped test guards nothing


def _env():
    """Jinja with the Ansible filters these expressions use.

    `from_json` and `equalto` ship with Ansible rather than stock Jinja, so a
    bare Environment cannot render the real conditions.
    """
    env = jinja2.Environment()
    env.filters["from_json"] = json.loads
    env.tests["equalto"] = lambda value, other: value == other
    return env


def _render(expression: str, **context):
    return _env().from_string("{{ " + expression + " }}").render(**context) == "True"


def _condition_of(name_fragment: str) -> str:
    for task in _tasks():
        if name_fragment.lower() in str(task.get("name", "")).lower():
            return str(task.get("when", ""))
    raise AssertionError(f"no task matching {name_fragment!r}")


def _fact_of(name_fragment: str, key: str) -> str:
    for task in _tasks():
        if name_fragment.lower() in str(task.get("name", "")).lower():
            return str(task["ansible.builtin.set_fact"][key])
    raise AssertionError(f"no set_fact task matching {name_fragment!r}")


def test_a_similar_user_does_not_suppress_creating_this_one():
    """'svc@pve' is a substring of 'xsvc@pve'. Matching raw JSON text would
    skip creating an account that does not exist, and the play would then
    grant ACLs to a phantom user and report success."""
    userids = ["xsvc@pve", "root@pam"]

    should_create = _render(_condition_of("Create the service account"),
                            token_user="svc", token_realm="pve",
                            existing_userids=userids)

    assert should_create, "creation was skipped for a user that does not exist"


def test_an_existing_user_does_suppress_creating_it_again():
    should_create = _render(_condition_of("Create the service account"),
                            token_user="svc", token_realm="pve",
                            existing_userids=["svc@pve"])

    assert not should_create


def test_a_similar_token_name_does_not_suppress_creating_this_one():
    """A token 'mcp' is a substring of an existing 'mcp-readonly'."""
    should_create = _render(_condition_of("Create the token"),
                            token_name="mcp",
                            existing_tokenids=["mcp-readonly"])

    assert should_create, "no token named 'mcp' would ever have been issued"


def test_an_existing_token_is_not_reissued():
    should_create = _render(_condition_of("Create the token"),
                            token_name="mcp", existing_tokenids=["mcp"])

    assert not should_create


def test_the_acl_extraction_matches_path_role_and_exact_ugid():
    """A grant for an unrelated role or path must not satisfy verification."""
    acl = json.dumps([
        {"path": "/vms", "roleid": "PVEAuditor", "ugid": "svc@pve"},
        {"path": "/vms", "roleid": "PVEAuditor", "ugid": "svc@pve!mcp"},
        {"path": "/", "roleid": "PVEAdmin", "ugid": "other@pve"},
        {"path": "/vms", "roleid": "PVEAdmin", "ugid": "wrong-role@pve"},
    ])

    # The set_fact value already carries its own {{ }}, so render it as-is.
    rendered = _env().from_string(
        _fact_of("Extract the grants", "acl_ugids")
    ).render(acl_list={"stdout": acl}, token_path="/vms", token_role="PVEAuditor")

    assert "svc@pve!mcp" in rendered
    assert "wrong-role@pve" not in rendered
    assert "other@pve" not in rendered


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
