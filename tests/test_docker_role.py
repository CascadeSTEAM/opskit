"""ansible/roles/docker (opskit #241): one shared Docker-install role instead
of two drifting inline copies in install-docker.yml and
provision-runner-lxc.yml, plus a tightened idempotency precondition.

Two failure modes motivate these tests:

1. **Precondition too loose.** A bare `docker --version` check passes on a
   host with distro docker.io, a snap package, or an old CE install missing
   the Compose v2 plugin — exactly the precondition this role exists to
   guarantee for compose-based stack roles. The check must specifically
   verify `docker compose version`.
2. **Duplication creeping back.** provision-runner-lxc.yml's guest-prep play
   must delegate to the shared role rather than re-inlining its own Docker
   apt-repo logic, or a future fix (like the /etc/apt/keyrings gap already
   hit once) has to be applied twice again.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE_TASKS = ROOT / "ansible" / "roles" / "docker" / "tasks" / "main.yml"
INSTALL_DOCKER = ROOT / "ansible" / "playbooks" / "install-docker.yml"
RUNNER_LXC = ROOT / "ansible" / "playbooks" / "provision-runner-lxc.yml"


def _role_tasks():
    return yaml.safe_load(ROLE_TASKS.read_text())


def _flatten(tasks):
    out = []
    for task in tasks:
        out.append(task)
        out.extend(_flatten(task.get("block", [])))
    return out


def _module_of(task):
    for key in task:
        if key.startswith("ansible.builtin.") or key.startswith("community."):
            return key
    return None


def test_precondition_checks_compose_v2_not_bare_docker_version():
    tasks = _flatten(_role_tasks())
    precondition = next(t for t in tasks if t.get("register") == "docker_check")
    assert precondition["ansible.builtin.command"] == "docker compose version", (
        "a bare 'docker --version' check would pass on a host with some "
        "Docker already present but no Compose v2 plugin, silently failing "
        "to guarantee the precondition this role exists to satisfy"
    )


def test_install_is_gated_on_the_precondition():
    tasks = _role_tasks()
    install_block = next(t for t in tasks if t.get("block"))
    assert install_block["when"] == "docker_check.rc != 0"


def test_keyrings_directory_is_created_before_the_gpg_key_is_fetched():
    tasks = _flatten(_role_tasks())
    names = [t.get("name", "") for t in tasks]
    mkdir_idx = next(i for i, n in enumerate(names) if "keyrings exists" in n)
    geturl_idx = next(i for i, n in enumerate(names) if "GPG key" in n)
    assert mkdir_idx < geturl_idx, (
        "get_url never creates its destination's parent directory, and "
        "/etc/apt/keyrings doesn't exist by default on Debian 11/Ubuntu 20.04"
    )


def test_distro_is_asserted_before_any_apt_repo_is_added():
    tasks = _flatten(_role_tasks())
    names = [t.get("name", "") for t in tasks]
    assert_idx = next(i for i, n in enumerate(names) if "doesn't know how to handle" in n)
    repo_idx = next(i for i, n in enumerate(names) if "Add the Docker apt repository" in n)
    assert assert_idx < repo_idx


def test_registered_vars_use_the_role_prefix():
    """ansible-lint's var-naming[no-role-prefix] rule, pinned so it can't
    regress silently — a role-scoped register without the role's own name
    prefix is exactly the class of thing a linter catches once and a rename
    six months later reintroduces."""
    tasks = _flatten(_role_tasks())
    registered = [t["register"] for t in tasks if "register" in t]
    assert registered, "expected at least one registered var in the role"
    for name in registered:
        assert name.startswith("docker_"), f"{name!r} should be docker_-prefixed"


def test_install_docker_playbook_uses_the_shared_role():
    play = yaml.safe_load(INSTALL_DOCKER.read_text())[0]
    assert play["hosts"] == "{{ target_host }}", (
        "no default — every other apt-installing playbook in this repo "
        "requires target_host explicitly rather than falling back to 'all'"
    )
    roles = play.get("roles", [])
    role_names = [r["role"] if isinstance(r, dict) else r for r in roles]
    assert "docker" in role_names


def test_runner_lxc_guest_prep_delegates_to_the_shared_role_not_an_inline_copy():
    plays = yaml.safe_load(RUNNER_LXC.read_text())
    guest_prep = next(p for p in plays if "base guest" in p["name"])
    tasks = _flatten(guest_prep["tasks"])

    include_role_tasks = [
        t for t in tasks
        if t.get("ansible.builtin.include_role", {}).get("name") == "docker"
        or t.get("include_role", {}).get("name") == "docker"
    ]
    assert include_role_tasks, (
        "guest-prep play must delegate Docker install to ansible/roles/docker "
        "rather than carrying its own inline apt-repo block"
    )

    # No inline Docker-repo logic left behind to drift from the shared role.
    modules_used = {_module_of(t) for t in tasks if _module_of(t)}
    assert "ansible.builtin.deb822_repository" not in modules_used, (
        "found an inline Docker apt-repo task in provision-runner-lxc.yml -- "
        "this duplication is exactly what opskit#241 removed"
    )
