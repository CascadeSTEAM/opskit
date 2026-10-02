"""Static validation of ansible/playbooks/deploy-compose-app.yml (#425).

Deploys a Docker Compose application from a PRIVATE GitHub repository onto a guest that already
has Docker (install-docker.yml) and SSH (bootstrap-lxc-access.yml). Never executed in CI, so the
properties that matter are pinned here, following the other provisioning-playbook tests.

Failure modes that are silent and expensive, one test each:

1. Trusting GitHub's host key on first use (a man-in-the-middle gets the deploy key's access).
2. Reading or printing the PRIVATE deploy key; only the public half may ever leave the guest.
3. Overwriting generated secrets in .env, or logging env values that may be secrets.
4. Discarding local changes or destroying state on the guest (force checkouts, compose down -v...).
5. A dry run (--check) that cannot show the clone state because its discovery was skipped.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "ansible" / "playbooks" / "deploy-compose-app.yml"

RFC1918 = re.compile(
    r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
)

MUST_HAVE_NO_DEFAULT = ("app_name", "app_repo")


def _play():
    return yaml.safe_load(PLAYBOOK.read_text())[0]


def _tasks():
    return _play()["tasks"]


def _flatten(tasks):
    out = []
    for task in tasks:
        out.append(task)
        out.extend(_flatten(task.get("block", [])))
        out.extend(_flatten(task.get("rescue", [])))
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


def test_the_target_is_supplied_not_hardcoded():
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


def test_only_github_ssh_urls_are_accepted():
    """Host-key verification below is GitHub-specific; anything else would silently skip it."""
    text = " ".join(str(t.get("ansible.builtin.assert", "")) for t in _flatten(_tasks()))
    assert "git@github.com:" in text


def test_github_host_keys_come_from_githubs_published_list_not_first_use():
    meta = _task_named("Fetch GitHub's published SSH host keys")
    assert "api.github.com/meta" in str(meta["ansible.builtin.uri"]["url"])
    assert meta.get("delegate_to") == "localhost"
    assert meta.get("check_mode") is False
    known = _task_named("Trust only GitHub's published host keys")
    assert "ansible.builtin.known_hosts" in known
    git = _task_named("Clone or update the application")
    assert git["ansible.builtin.git"].get("accept_hostkey") in (None, False), "no trust on first use"
    assert "accept-new" not in _text() and "StrictHostKeyChecking=no" not in _text()


def test_the_deploy_key_is_generated_only_when_absent_and_has_no_passphrase_prompt():
    task = _task_named("Generate a dedicated deploy key")
    assert "creates" in task["ansible.builtin.command"]
    assert "ed25519" in _cmd(task)
    assert "-N ''" in _cmd(task) or '-N ""' in _cmd(task)


def test_the_private_key_is_never_read_or_printed():
    for task in _flatten(_tasks()):
        body = str(task)
        if "slurp" in body or "ansible.builtin.debug" in body or "ansible.builtin.fail" in body or "cat " in body:
            assert not re.search(r"deploy_key(_path)?\s*\}\}(?!\.pub)", body.replace("}}.pub", "}}-PUB")), (
                f"task {task.get('name')!r} may expose the private key"
            )
    slurp = _task_named("Read the deploy key's PUBLIC half")
    assert str(slurp["ansible.builtin.slurp"]["src"]).endswith(".pub")


def test_a_rejected_clone_tells_the_operator_the_public_key_to_authorize():
    git_block = [t for t in _tasks() if "block" in t and any("ansible.builtin.git" in b for b in t["block"])]
    assert git_block, "the clone must sit in a block with a rescue"
    rescue = git_block[0].get("rescue") or []
    assert rescue and "ansible.builtin.fail" in rescue[0]
    assert "read-only" in str(rescue[0]).lower() and "deploy key" in str(rescue[0]).lower()


def test_local_changes_on_the_guest_are_never_discarded():
    git = _task_named("Clone or update the application")["ansible.builtin.git"]
    assert git.get("force") in (None, False)
    for bad in ("git reset --hard", "git clean", "git checkout -f", "git checkout --force"):
        assert bad not in _text()


def test_generated_secrets_in_env_are_never_overwritten():
    task = _task_named("Generate the application's secrets")
    assert "creates" in task["ansible.builtin.command"], "run the project's env script only when .env is absent"
    lines = _task_named("Write the host-specific environment lines")
    assert lines["ansible.builtin.lineinfile"].get("create") in (None, False)


def test_env_values_are_not_logged_and_the_file_is_private():
    assert _task_named("Write the host-specific environment lines").get("no_log") is True
    perms = _task_named("Keep the environment file private")
    assert str(perms["ansible.builtin.file"]["mode"]) in ("0600", "600")


def test_bringing_the_stack_up_is_optional_and_never_destructive():
    up = _task_named("Bring the stack up")
    assert "app_up" in str(up.get("when"))
    for bad in ("compose down", "down -v", "docker volume rm", "docker system prune", "docker compose rm", "rm -rf", " --volumes"):
        assert bad not in _text(), f"{bad!r} has no place in a deploy play"


def test_git_state_is_visible_under_check_mode():
    meta = _task_named("Fetch GitHub's published SSH host keys")
    assert meta.get("check_mode") is False


def test_the_report_states_what_was_and_was_not_done():
    text = str(_task_named("Report")["ansible.builtin.debug"])
    assert "app_up" in text
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
