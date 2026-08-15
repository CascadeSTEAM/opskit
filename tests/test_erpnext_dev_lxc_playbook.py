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

import pytest
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


def _with_guards(tasks, inherited=""):
    """(task, effective_guard) pairs — a task in a block is also gated by the
    block's own `when`, so checking only the task's `when` understates it."""
    out = []
    for task in tasks:
        guard = f"{inherited} {task.get('when', '')}".strip()
        out.append((task, guard))
        out.extend(_with_guards(task.get("block", []), guard))
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


# Modules that only read or report. Anything else in this play changes state.
# Keep this list honest: an entry here exempts a task from the guard below, so
# adding one is a claim that the module cannot change the target.
READ_ONLY_MODULES = {
    "ansible.builtin.assert",
    "ansible.builtin.debug",
    "ansible.builtin.set_fact",
    "ansible.builtin.slurp",   # fetches a file's contents; writes nothing
    "ansible.builtin.stat",    # reports file metadata; writes nothing
}


def _module_of(task):
    for key in task:
        if key.startswith("ansible.builtin."):
            return key
    return None


def _mutating_tasks():
    """Every state-changing task with its effective guard, found by module
    rather than by grepping for 'pct create'. An earlier version of this test
    matched command substrings and silently skipped the firewall copy and the
    template download, so removing their guards went undetected."""
    out = []
    for task, guard in _with_guards(_tasks()):
        module = _module_of(task)
        if module is None or module in READ_ONLY_MODULES:
            continue
        if task.get("block"):
            continue  # the block wrapper itself performs nothing
        # A read-only command declares itself with changed_when: false.
        if task.get("changed_when") is False:
            continue
        out.append((task, guard))
    return out


def test_creation_only_runs_when_the_container_is_absent():
    """Every mutating task must be conditioned on the probe, or a re-run
    reshapes a container that already exists."""
    mutating = _mutating_tasks()
    assert len(mutating) >= 4, (
        f"expected the create/template/firewall/start tasks, found "
        f"{[t.get('name') for t, _ in mutating]} — did the play change shape?"
    )

    for task, guard in mutating:
        assert "existing_ct" in guard, (
            f"task {task.get('name')!r} would run against an existing container"
        )


def test_firewall_rules_file_presence_is_verified_on_every_run():
    """opskit #240: the create-only gate means a container created but whose
    rules-file write failed on a prior run is never re-attempted — the
    'already exists' branch skips straight past it. This check must run
    regardless of existing_ct, so that gap fails loudly instead of silently
    leaving an unfirewalled container behind."""
    stat_tasks = [
        t for t in _flatten(_tasks())
        if t.get("ansible.builtin.stat", {}).get("path") == "/etc/pve/firewall/{{ ct_id }}.fw"
    ]
    assert stat_tasks, "nothing checks whether the rules file actually exists"
    for task, guard in _with_guards(_tasks()):
        if task in stat_tasks:
            assert "existing_ct" not in guard, (
                "the rules-file existence check must not be gated on "
                "existing_ct, or it never runs for a container that already "
                "exists — exactly the case this test guards against"
            )


def test_a_missing_firewall_rules_file_fails_the_run_loudly():
    asserts = [
        t for t in _flatten(_tasks())
        if "ansible.builtin.assert" in t
        and "ct_firewall_rules_file" in str(t["ansible.builtin.assert"].get("that", ""))
    ]
    assert asserts, "nothing asserts on the rules-file stat result"
    condition = str(asserts[0]["ansible.builtin.assert"]["that"])
    assert "stat.exists" in condition

    for task, guard in _with_guards(_tasks()):
        if task in asserts:
            assert "existing_ct" not in guard, (
                "the loud-failure assert must also run unconditionally, or "
                "an existing container with a missing rules file passes silently"
            )


def test_no_task_sets_a_mode_on_the_proxmox_cluster_filesystem():
    """/etc/pve is pmxcfs, a FUSE filesystem that rejects chmod() with EPERM.
    The copy module chmods after writing, so a `mode:` there fails the run
    partway through provisioning — after the container already exists."""
    for task in _flatten(_tasks()):
        module = _module_of(task) or ""
        args = task.get(module) if isinstance(task.get(module), dict) else {}
        dest = str(args.get("dest", ""))
        if dest.startswith("/etc/pve"):
            assert "mode" not in args, (
                f"task {task.get('name')!r} sets mode on {dest}; pmxcfs rejects "
                f"chmod and the task will fail on a real node"
            )


def test_keyctl_is_only_requested_for_unprivileged_containers():
    """Proxmox documents keyctl as unprivileged-only."""
    text = PLAYBOOK.read_text()
    assert "',keyctl=1' if ct_unprivileged else ''" in text, (
        "keyctl must be conditional on ct_unprivileged"
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
    clone of Confidential data.

    All THREE conditions Proxmox requires, not two of them (#187). Asserting
    only the guest-side pair locked in a configuration that a disabled
    datacenter firewall makes entirely inert, while the run still reported the
    container isolated."""
    text = PLAYBOOK.read_text()
    assert "policy_in: DROP" in text          # guest rules file
    assert "firewall=1" in text               # vNIC flag
    assert "cluster.fw" in text               # datacenter switch


def test_the_datacenter_firewall_is_checked_before_anything_is_created():
    """A refusal must cost nothing. Checking after `pct create` would leave a
    half-provisioned node behind on every failure."""
    names = [str(t.get("name", "")) for t in _flatten(_tasks())]
    check = next(i for i, n in enumerate(names) if "datacenter firewall" in n.lower())
    create = next(i for i, n in enumerate(names) if n == "Create the container")

    assert check < create, "the precondition is asserted too late to be free"


def test_the_isolation_claim_is_conditional_on_the_precondition():
    """The wording must track reality: an unconditional 'network-isolated' is
    the statement an operator relies on when deciding not to look further."""
    reports = [
        str(t["ansible.builtin.debug"]["msg"])
        for t in _flatten(_tasks()) if "ansible.builtin.debug" in t
    ]
    isolation_claims = [r for r in reports if "ISOLATED" in r.upper()]
    assert isolation_claims, "the report says nothing about isolation at all"

    for claim in isolation_claims:
        assert "datacenter_firewall_on" in claim, (
            "an isolation claim that does not depend on the precondition is a "
            "claim about outcome made from a check that was never done"
        )


# ── the detection itself, rendered rather than grepped (#187 review) ─────────
#
# file_exists models the structural stat check the play now does BEFORE
# slurp, rather than inferring "file absent" from slurp's own error text —
# that text-matching approach broke live once, on a node whose cluster.fw
# didn't exist at all: this ansible-core version's slurp says "File not
# found: ...", not the "No such file" the check was originally written
# against, misclassifying "off" as "unreadable" and refusing to proceed
# even with the isolation requirement explicitly overridden (opskit #209).

def _render_firewall_expr(name, cluster_fw_text=None, msg="", file_exists=True):
    """Render one of the real set_fact expressions against a fixture."""
    import base64
    import jinja2

    task = next(t for t in _flatten(_tasks())
                if "Establish whether" in str(t.get("name", "")))
    expr = task["ansible.builtin.set_fact"][name]

    env = jinja2.Environment()
    env.filters["b64decode"] = lambda s: base64.b64decode(s).decode()
    env.filters["regex_findall"] = lambda s, p: re.findall(p, s)
    env.filters["last"] = lambda seq: seq[-1] if seq else None

    ctx = {
        "cluster_fw": {"msg": msg},
        "cluster_fw_stat": {"stat": {"exists": file_exists}},
    }
    if cluster_fw_text is not None:
        ctx["cluster_fw"]["content"] = base64.b64encode(
            cluster_fw_text.encode()).decode()
    return env.from_string(expr).render(**ctx).strip() == "True"


def _render_firewall_detection(cluster_fw_text=None, msg="", file_exists=True):
    return _render_firewall_expr(
        "datacenter_firewall_on", cluster_fw_text, msg, file_exists)


def _render_unreadable(cluster_fw_text=None, msg="", file_exists=True):
    return _render_firewall_expr(
        "datacenter_firewall_unreadable", cluster_fw_text, msg, file_exists)


@pytest.mark.parametrize("content,expected", [
    ("[OPTIONS]\nenable: 1\n", True),
    ("[OPTIONS]\nenable: 0\n", False),
    ("[OPTIONS]\nenable:1\n", True),          # no space
    ("[OPTIONS]\n# enable: 1\n", False),      # commented out
    ("", False),                              # empty file
    ("[RULES]\n", False),                     # no OPTIONS section
    ("[OPTIONS]\r\nenable: 1\r\n", True),     # CRLF
    # A leftover second block from a bad edit or restore: the LAST value is the
    # effective one, so an earlier `enable: 1` must not mask it. Matching the
    # first occurrence anywhere in the file gave the wrong answer in the
    # dangerous direction.
    ("[OPTIONS]\nenable: 1\n\n[RULES]\n\n[OPTIONS]\nenable: 0\n", False),
    ("[OPTIONS]\nenable: 0\n\n[OPTIONS]\nenable: 1\n", True),
])
def test_the_firewall_switch_is_read_correctly(content, expected):
    assert _render_firewall_detection(content) is expected


def test_an_absent_file_reads_as_off_not_unreadable():
    """The structural fix, rendered: a file that plain doesn't exist is
    "off", never "unreadable" — regardless of what message a future
    ansible-core version's slurp happens to report for a missing file."""
    assert _render_firewall_detection(None, file_exists=False) is False
    assert _render_unreadable(None, file_exists=False) is False


def test_a_present_but_unreadable_file_is_flagged_unreadable():
    """The file exists (stat confirms it) but slurp still couldn't read
    it — a real permissions/connection problem, not "off"."""
    assert _render_firewall_detection(None, msg="Permission denied", file_exists=True) is False
    assert _render_unreadable(None, msg="Permission denied", file_exists=True) is True


def test_an_unrecognised_opt_out_value_is_refused_not_read_as_false():
    """Ansible's `bool` filter maps any unrecognised string to false without
    complaint, so a bare, unguarded `| bool` on this variable would let a
    typo like `-e require_datacenter_firewall=treu` silently disable the
    guard. But omitting `| bool` entirely has its own live-caught failure
    mode: `-e require_datacenter_firewall=false` arrives as the STRING
    "false" — truthy in Jinja — so an unguarded `not
    require_datacenter_firewall` never fires even when explicitly opted out
    (opskit #209, hit live). The actual invariant is order, not absence:
    `| bool` may only be applied to this variable AFTER the strict
    literal-list assert has already run, so anything reaching it is
    guaranteed to already be a known-good spelling."""
    asserts = [
        (i, t) for i, t in enumerate(_flatten(_tasks()))
        if "ansible.builtin.assert" in t
    ]

    def _that(t):
        return str(t["ansible.builtin.assert"].get("that", ""))

    literal_list_idx = next(
        i for i, t in asserts if "require_datacenter_firewall in [" in _that(t)
    )
    assert literal_list_idx is not None, "the opt-out must accept only exact literals"

    bool_cast_idx = next(
        (i for i, t in asserts if "require_datacenter_firewall | bool" in _that(t)),
        None,
    )
    assert bool_cast_idx is not None, (
        "require_datacenter_firewall must be cast with | bool where it's "
        "actually used, or the string 'false' from "
        "-e require_datacenter_firewall=false is truthy and the opt-out "
        "never fires"
    )
    assert literal_list_idx < bool_cast_idx, (
        "| bool must only be applied after the strict literal-list assert "
        "has already run — using it before, or instead of, that validation "
        "lets an unrecognised value like 'treu' silently become false"
    )


def test_an_unreadable_file_is_not_reported_as_a_disabled_firewall():
    """A permissions error must not read as 'firewall off' — that message
    sends the operator to the GUI, and nudges them toward disabling the check
    to 'fix' a blocked run, turning a read failure into a real exposure."""
    text = PLAYBOOK.read_text()
    assert "datacenter_firewall_unreadable" in text
    assert "Could NOT READ" in text
    assert "Do NOT reach for require_datacenter_firewall=false" in text


def test_proceeding_without_isolation_requires_saying_so():
    text = PLAYBOOK.read_text()
    assert "require_datacenter_firewall" in text
    assert _play()["vars"]["require_datacenter_firewall"] is True, (
        "the safe posture must be the default, not the opt-in"
    )


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
        "target_host", "existing_ct", "template_list", "cluster_fw_stat",
    }

    referenced = set(re.findall(r"\{\{\s*([a-z_][a-z0-9_]*)", PLAYBOOK.read_text()))
    unknown = referenced - known

    assert not unknown, f"undeclared variables referenced: {sorted(unknown)}"
