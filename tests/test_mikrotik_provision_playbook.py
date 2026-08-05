"""Tests for ansible/playbooks/mikrotik-provision-mcp-readonly-user.yml.

This playbook is the rebuild path for the scoped API user that mikromcp itself
logs in with (opskit #105, ledger row 29). Two things about it are worth pinning
down in CI, because both failure modes are silent and expensive:

1. It must never reach for `api_modify` on an account path. That module
   converges a whole path against a `data` list — pointed at `user` with a
   wrong payload it removes every other account on the device, which is the
   class of mistake #94 documents in the sibling playbook. Reading with
   `api_info` and adding with `api` cannot delete anything.

2. The group policy must stay byte-identical to what is deployed. It was read
   off a live router rather than composed by hand; a rebuild that silently
   widens the account's permissions defeats the point of it being read-only.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "mikrotik-provision-mcp-readonly-user.yml"

# Read from the deployed router with `mikromcp list_user_groups` on 2026-08-04.
# If RouterOS or the deployment genuinely changes, re-read it from the device
# and update this constant — do not edit it to match a failing playbook.
DEPLOYED_POLICY = (
    "read,api,rest-api,!local,!telnet,!ssh,!ftp,!reboot,!write,!policy,"
    "!test,!winbox,!password,!web,!sniff,!sensitive,!romon"
)


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def test_playbook_exists():
    """Ledger row 29: a vault item credited this file while it existed nowhere."""
    assert PLAYBOOK.is_file()


def test_group_policy_matches_the_deployed_router():
    rendered = re.sub(r"\s+", "", _play()["vars"]["mcp_group_policy"])

    assert rendered == DEPLOYED_POLICY


def test_policy_grants_only_read_api_and_rest_api():
    """Every non-negated policy must be one of the three the tool actually needs."""
    granted = [p for p in DEPLOYED_POLICY.split(",") if not p.startswith("!")]

    assert sorted(granted) == ["api", "read", "rest-api"]


def test_write_and_policy_permissions_are_explicitly_negated():
    """Negating rather than omitting means a future RouterOS default cannot
    silently widen the account."""
    for dangerous in ("write", "policy", "reboot", "ssh", "telnet", "ftp"):
        assert f"!{dangerous}" in DEPLOYED_POLICY.split(",")


def test_no_api_modify_anywhere_in_the_playbook():
    """The destructive-module guard — see this module's docstring."""
    modules = {key for task in _tasks() for key in task if "." in key}

    assert not any("api_modify" in m for m in modules), (
        "api_modify converges a whole path and can delete accounts; "
        "use api_info to read and api to add"
    )


def test_account_creation_is_guarded_by_an_existence_check():
    """Idempotency: adds run only when the entity is absent."""
    adds = [t for t in _tasks() if "community.routeros.api" in t]

    assert adds, "no creation tasks found"
    for task in adds:
        conditions = " ".join(task.get("when", []))
        assert "not in" in conditions, f"{task['name']} is not guarded"
        assert "not ansible_check_mode" in conditions, (
            f"{task['name']} would run during --check"
        )


def test_the_user_creation_task_does_not_log_its_password():
    user_adds = [
        t for t in _tasks()
        if "community.routeros.api" in t
        and "mcp_user_password" in str(t["community.routeros.api"].get("add", ""))
    ]

    assert user_adds, "no user creation task found"
    for task in user_adds:
        assert task.get("no_log") is True


def test_playbook_refuses_to_invent_a_password():
    """no-plaintext-creds: a generated password would need persisting somewhere."""
    body = PLAYBOOK.read_text()
    asserts = [t for t in _tasks() if "ansible.builtin.assert" in t]

    assert asserts, "no precondition assert"
    conditions = " ".join(asserts[0]["ansible.builtin.assert"]["that"])
    assert "mcp_user_password is defined" in conditions
    assert "length >= 16" in conditions
    for generator in ("random(", "lookup('password'", 'lookup("password"'):
        assert generator not in body
