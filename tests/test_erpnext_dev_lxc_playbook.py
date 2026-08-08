"""Static validation of ansible/playbooks/provision-erpnext-dev-lxc.yml (#150).

The playbook is never executed in CI — creating a container needs a live
Proxmox node — so the properties that matter are pinned here instead, following
the precedent of tests/test_mikrotik_provision_playbook.py.

Three failure modes are silent and expensive, which is why each gets a test:

1. **Adopting an occupied container ID.** `pct create` against an in-use ID
   fails, but a play that reconfigures whatever it finds would quietly
   reshape someone else's container. The play must refuse.
2. **Inventing an address.** The container's address is not yet allocated. A
   default would either collide with a live host or produce an unreachable
   container, and both look like success from the playbook's side.
3. **Losing the Docker-in-LXC flags.** Without nesting and keyctl, Docker
   fails inside an unprivileged container in ways that read as a Docker
   problem rather than a container-config problem.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "provision-erpnext-dev-lxc.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)

# Variables the play requires the caller to supply. Giving any of these a
# default is the defect, not a convenience.
MUST_HAVE_NO_DEFAULT = ("ct_id", "ct_ip", "ct_gateway")


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def _flatten(tasks):
    """Tasks including those nested in a block."""
    out = []
    for task in tasks:
        out.append(task)
        out.extend(_flatten(task.get("block", [])))
    return out


def test_playbook_exists_and_parses():
    assert PLAYBOOK.is_file()
    assert isinstance(_play(), dict)


def test_it_hardcodes_no_infrastructure_addresses():
    """#134's rule applies to new files too: committed playbooks stay
    environment-agnostic."""
    assert not RFC1918.search(PLAYBOOK.read_text())


def test_the_unallocated_values_have_no_defaults():
    """A default address is a guess about someone else's network."""
    defaults = _play().get("vars", {})
    for name in MUST_HAVE_NO_DEFAULT:
        assert name not in defaults, (
            f"{name} must have no default — the play must fail loudly rather "
            f"than invent one"
        )


def test_it_asserts_the_required_variables_are_supplied():
    asserts = [t for t in _flatten(_tasks()) if "ansible.builtin.assert" in t]
    assert asserts, "nothing validates the required parameters"

    conditions = " ".join(
        str(t["ansible.builtin.assert"].get("that", "")) for t in asserts
    )
    for name in MUST_HAVE_NO_DEFAULT:
        assert f"{name} is defined" in conditions, f"{name} is never checked"


def test_it_refuses_a_container_id_that_belongs_to_something_else():
    """The idempotency contract: never recreate, never destroy, never adopt."""
    text = PLAYBOOK.read_text()
    assert "Refusing to adopt or overwrite" in text

    guarded = [
        t for t in _flatten(_tasks())
        if "ansible.builtin.assert" in t and "existing_ct" in str(t.get("when", ""))
    ]
    assert guarded, "no assert is gated on the existing-container probe"


def test_creation_only_runs_when_the_container_is_absent():
    """Every mutating task must be conditioned on the probe, or a re-run
    reshapes a container that already exists."""
    mutating = [
        t for t in _flatten(_tasks())
        if any(k.startswith("ansible.builtin.") and k != "ansible.builtin.assert"
               and k not in ("ansible.builtin.debug",)
               for k in t)
        and "pct create" in str(t) or "pct set" in str(t) or "pct start" in str(t)
    ]
    assert mutating, "no container-mutating task found — did the play change shape?"

    for task in mutating:
        assert "existing_ct" in str(task.get("when", "")), (
            f"task {task.get('name')!r} would run against an existing container"
        )


def test_the_probe_never_fails_the_run():
    """`pct config` on a free ID exits non-zero; that is the normal path."""
    probe = [t for t in _flatten(_tasks()) if "pct config" in str(t)]
    assert probe, "nothing probes for an existing container"
    assert probe[0].get("failed_when") is False
    assert probe[0].get("changed_when") is False


def test_docker_in_lxc_features_are_set():
    """nesting for namespaces, keyctl for containerd's keyring use."""
    text = PLAYBOOK.read_text()
    assert "nesting=1" in text
    assert "keyctl=1" in text


def test_the_container_is_network_isolated_by_default():
    """No port forwarding, no default-permit rules — it will later hold a
    clone of Confidential data."""
    text = PLAYBOOK.read_text()
    assert "policy_in: DROP" in text
    assert "firewall=1" in text


def test_sizing_defaults_are_generous_and_overridable():
    """The production deployment this mirrors is disk-constrained, and that
    constraint is explicitly not reproduced here."""
    v = _play()["vars"]
    assert v["ct_disk_gb"] >= 100
    assert v["ct_memory_mb"] >= 4096
    assert v["ct_cores"] >= 2


def test_every_referenced_variable_is_defined_or_required():
    """A typo'd variable renders empty and produces a malformed pct command."""
    declared = set(_play().get("vars", {})) | set(MUST_HAVE_NO_DEFAULT)
    # Supplied at run time, like target_host; plus loop/register names.
    known = declared | {
        "target_host", "existing_ct", "template_list",
    }

    referenced = set(re.findall(r"\{\{\s*([a-z_][a-z0-9_]*)", PLAYBOOK.read_text()))
    unknown = referenced - known

    assert not unknown, f"undeclared variables referenced: {sorted(unknown)}"
